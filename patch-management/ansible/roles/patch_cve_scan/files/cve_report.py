#!/usr/bin/env python3
"""Scan collected package lists and image digests with Trivy and write a CVE report.

Input (all under --workdir, written by playbooks/cve-scan.yml):
  rootfs/<host>/etc/os-release, var/lib/dpkg/status   fetched from SSH hosts
  lxc/<node>.json                                     files read from containers via pct exec
  images/<host>.json                                  running images with their registry digests
  settings.json, kev.json                             threshold, exposure lists, CISA KEV list
Output: cve-report.md and cve-report.json in --reports-dir. Nothing is changed anywhere.
"""
import argparse
import concurrent.futures
import datetime
import glob
import json
import os
import subprocess
import sys
import time

SEVERITY_SCORE = {"CRITICAL": 9.0, "HIGH": 7.5, "MEDIUM": 5.0, "LOW": 2.0}
TIER_RANK = {"direct": 0, "tunnel": 1, "internal": 2}
TIER_LABEL = {"direct": "direct (home IP)", "tunnel": "via tunnel", "internal": "internal/unknown"}


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def run_trivy(trivy, args, attempts=3):
    """Run trivy and return (json, error). Registry limits and dropped layers are retried."""
    cmd = [trivy] + args + ["--quiet", "--format", "json", "--scanners", "vuln",
                            "--skip-db-update", "--skip-java-db-update"]
    err = "trivy failed"
    for attempt in range(attempts):
        if attempt:
            time.sleep(45 * attempt)
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
        except subprocess.TimeoutExpired:
            err = "timed out"
            continue
        if p.returncode == 0:
            try:
                return json.loads(p.stdout), None
            except ValueError:
                return None, "unreadable trivy output"
        err = " ".join(p.stderr.split())[-400:] or "trivy failed"
        if "UNAUTHORIZED" in err:  # a missing or private image will not get better
            break
    return None, err


def score_of(vuln):
    best = None
    for src in (vuln.get("CVSS") or {}).values():
        s = src.get("V3Score")
        if s is not None and (best is None or s > best):
            best = s
    if best is not None:
        return best, False
    return SEVERITY_SCORE.get(vuln.get("Severity", ""), 0.0), True  # estimated from the label


def tier_for(text, exposure):
    text = text.lower()
    for tier in ("direct", "tunnel"):
        if any(k.lower() in text for k in exposure.get(tier, [])):
            return tier
    return "internal"


def parse(report, target, kind, tier, min_cvss, kev):
    """Return (findings that need attention, findings the distro rates lower, other count, os info).

    A finding needs attention if CISA lists it as exploited, or its CVSS score reaches the
    threshold AND the distro itself rates it HIGH or CRITICAL. NVD scores are often inflated for
    disputed or hard-to-exploit issues that Debian and Ubuntu rate low; those go in `downrated`.
    """
    attention, downrated, other = [], [], 0
    meta = ((report or {}).get("Metadata") or {}).get("OS") or {}
    for res in (report or {}).get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            score, estimated = score_of(v)
            cve = v.get("VulnerabilityID", "")
            sev = v.get("Severity", "")
            exploited = cve in kev
            row = {
                "target": target, "kind": kind, "exposure": tier, "cve": cve,
                "score": score, "estimated": estimated, "severity": sev, "kev": exploited,
                "package": v.get("PkgName", ""), "installed": v.get("InstalledVersion", ""),
                "fixed": v.get("FixedVersion", ""), "status": v.get("Status", ""),
            }
            if exploited or (score >= min_cvss and sev in ("HIGH", "CRITICAL")):
                attention.append(row)
            elif score >= min_cvss:
                downrated.append(row)
            else:
                other += 1
    return attention, downrated, other, meta


def merge(rows):
    """One row per (target, CVE): several packages often share a CVE."""
    merged = {}
    for r in rows:
        m = merged.setdefault((r["target"], r["cve"]), dict(r, packages=[], fixes=[]))
        m["packages"].append(r["package"])
        if r["fixed"]:
            m["fixes"].append(f"{r['package']} {r['fixed']}")
    out = []
    for m in merged.values():
        m["packages"] = sorted(set(m["packages"]))
        m["fixes"] = sorted(set(m["fixes"]))
        for k in ("package", "installed", "fixed"):
            m.pop(k, None)
        out.append(m)
    return out


def materialize_lxc(workdir):
    """Write the files read from containers into rootfs-style directories."""
    for path in glob.glob(os.path.join(workdir, "lxc", "*.json")):
        node = os.path.basename(path)[:-5]
        for f in load(path, []):
            root = os.path.join(workdir, "rootfs", f"{node}-ct{f['vmid']}-{f['name']}")
            dest = os.path.join(root, f["path"].lstrip("/"))
            os.makedirs(os.path.dirname(dest), mode=0o700, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(f["content"] + "\n")


def image_targets(workdir, exposure):
    """Group running containers by the registry digest of their image."""
    groups, unscannable = {}, []
    for path in sorted(glob.glob(os.path.join(workdir, "images", "*.json"))):
        host = os.path.basename(path)[:-5]
        for c in load(path, []):
            repo = c["ref"].split("@")[0].rsplit(":", 1)[0] if ":" in c["ref"].split("/")[-1] else c["ref"]
            digests = [d for d in c["digests"] if d]
            pick = next((d for d in digests if d.split("@")[0].endswith(repo.split("/", 1)[-1])), None) \
                or (digests[0] if digests else None)
            who = f"{host}:{c['name']}"
            tier = tier_for(f"{c['ref']} {c['name']} {c['project']}", exposure)
            if "@sha256:" in c["ref"] and not pick:
                pick = c["ref"]
            if not pick:
                unscannable.append({"target": who, "ref": c["ref"], "why": "no registry digest (local build?)"})
                continue
            g = groups.setdefault(pick, {"ref": c["ref"], "who": [], "tier": tier})
            g["who"].append(who)
            if TIER_RANK[tier] < TIER_RANK[g["tier"]]:
                g["tier"] = tier
    return groups, unscannable


def awareness(patch_report):
    """Things worth knowing even without a CVE, from the last check.yml run."""
    items = []
    for h in (patch_report or {}).get("hosts", []):
        name = h["name"]
        apt = h.get("apt")
        if apt:
            sec = len(apt.get("security", []))
            if apt.get("pending"):
                items.append(f"{name}: {len(apt['pending'])} package update(s) pending, {sec} marked security")
            if apt.get("reboot_required"):
                items.append(f"{name}: reboot required")
            if apt.get("held"):
                items.append(f"{name}: held packages never update: {', '.join(apt['held'])}")
        for c in (h.get("lxc") or {}).get("containers", []):
            if c.get("pending"):
                items.append(f"{name} CT {c['vmid']} {c['name']}: {len(c['pending'])} update(s) pending, "
                             f"{len(c.get('security', []))} security")
        tn = h.get("truenas")
        if tn and tn.get("update_status") == "AVAILABLE":
            items.append(f"{name}: TrueNAS {tn.get('update_version')} available (running {tn.get('version')})")
        if tn and "healthy" not in tn.get("pools", ""):
            items.append(f"{name}: pool status: {tn.get('pools')}")
        imgs = (h.get("docker") or {}).get("images", [])
        out = [i["image"] for i in imgs if i["status"] == "outdated"]
        unk = [i["image"] for i in imgs if i["status"] == "unknown"]
        if out:
            items.append(f"{name}: {len(out)} image(s) behind their registry tag: {', '.join(out)}")
        if unk:
            items.append(f"{name}: {len(unk)} image(s) could not be compared with the registry")
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--trivy", required=True)
    ap.add_argument("--reports-dir", required=True)
    ap.add_argument("--patch-report", default="")
    a = ap.parse_args()

    settings = load(os.path.join(a.workdir, "settings.json"), {})
    min_cvss = float(settings.get("min_cvss", 8.5))
    exposure = settings.get("exposure") or {}
    exposed_hosts = set(settings.get("exposed_hosts") or [])
    kev_raw = load(os.path.join(a.workdir, "kev.json"), None)
    kev = {v["cveID"] for v in (kev_raw or {}).get("vulnerabilities", [])}

    materialize_lxc(a.workdir)
    findings, downrated, lower, errors, eol, scanned = [], [], 0, [], [], []

    # 1. OS packages of hosts and containers (rootfs directories)
    for root in sorted(glob.glob(os.path.join(a.workdir, "rootfs", "*"))):
        target = os.path.basename(root)
        tier = "direct" if target in exposed_hosts else tier_for(target, exposure)
        rep, err = run_trivy(a.trivy, ["rootfs", "--pkg-types", "os", root])
        if err:
            errors.append(f"{target}: {err}")
            continue
        f, d, n, meta = parse(rep, target, "os packages", tier, min_cvss, kev)
        findings += f
        downrated += d
        lower += n
        scanned.append(target)
        if meta.get("EOSL"):
            eol.append(f"{target}: {meta.get('Family')} {meta.get('Name')} is past end of support")

    # 2. Running container images, pulled from the registry by digest
    groups, unscannable = image_targets(a.workdir, exposure)

    def scan_image(item):
        digest, g = item
        return digest, g, run_trivy(a.trivy, ["image", "--image-src", "remote", "--pkg-types", "os,library", digest])

    # One at a time: trivy's cache is locked by a running scan.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        for digest, g, (rep, err) in pool.map(scan_image, groups.items()):
            label = f"{g['ref']} ({', '.join(g['who'])})"
            if err:
                errors.append(f"{label}: {err}")
                continue
            f, d, n, meta = parse(rep, label, "image", g["tier"], min_cvss, kev)
            findings += f
            downrated += d
            lower += n
            scanned.append(label)
            if meta.get("EOSL"):
                eol.append(f"{label}: base OS {meta.get('Family')} {meta.get('Name')} is past end of support")

    findings = merge(findings)
    downrated = merge(downrated)
    findings.sort(key=lambda x: (TIER_RANK[x["exposure"]], not x["kev"], x["fixes"] == [], -x["score"], x["target"]))
    notes = awareness(load(a.patch_report, None))
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    result = {"generated": now, "min_cvss": min_cvss, "kev_loaded": bool(kev_raw),
              "attention": findings, "rated_lower_by_distro": downrated, "lower_findings": lower, "end_of_support": eol,
              "awareness": notes, "unscannable": unscannable, "errors": errors, "scanned": scanned}
    os.makedirs(a.reports_dir, exist_ok=True)
    with open(os.path.join(a.reports_dir, "cve-report.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    md = ["# CVE report", "", f"Generated {now}. Reporting only: nothing was changed.", "",
          f"Listed below: CISA known-exploited (KEV) CVEs, and CVEs with a CVSS score of {min_cvss} or "
          "more that the distro also rates HIGH or CRITICAL. Rows are per CVE and host; `fix` shows "
          "the package versions that contain the fix, or says none exists yet."
          + ("" if kev_raw else " **The KEV list could not be downloaded this time.**"), "",
          f"Not listed: {len(downrated)} CVE(s) scored {min_cvss}+ that the distro rates lower "
          "(often disputed or only exploitable in unusual setups; see `rated_lower_by_distro` in the "
          f"JSON) and {lower} below the threshold. A score marked `~` is estimated from the severity "
          "label.", "", "## Needs attention", ""]
    top = [x for x in findings if x["exposure"] == "direct" or x["kev"]]
    rest = [x for x in findings if x not in top]
    md += ["Directly exposed targets and known-exploited CVEs, in full:", ""]
    if top:
        md += ["| Exposure | Where | CVE | CVSS | Exploited | Packages | Fix |", "|---|---|---|---|---|---|---|"]
        for x in top:
            pk = ", ".join(x["packages"][:3]) + (f" (+{len(x['packages']) - 3})" if len(x["packages"]) > 3 else "")
            fix = "; ".join(x["fixes"][:2]) + (" ..." if len(x["fixes"]) > 2 else "") if x["fixes"] \
                else f"no fix yet ({x['status'] or 'unknown'})"
            md.append(f"| {TIER_LABEL[x['exposure']]} | {x['target']} | {x['cve']} | "
                      f"{'~' if x['estimated'] else ''}{x['score']} | {'**yes**' if x['kev'] else ''} | {pk} | {fix} |")
    else:
        md.append("Nothing matched.")
    if rest:
        by = {}
        for x in rest:
            t = by.setdefault(x["target"], {"exposure": x["exposure"], "n": 0, "fix": 0, "worst": 0.0})
            t["n"] += 1
            t["fix"] += bool(x["fixes"])
            t["worst"] = max(t["worst"], x["score"])
        md += ["", "Everything else that reached the threshold, per target (full detail in `cve-report.json`):", "",
               "| Where | Exposure | CVEs | With a fix | No fix yet | Highest CVSS |", "|---|---|---|---|---|---|"]
        for target, t in sorted(by.items(), key=lambda kv: (TIER_RANK[kv[1]["exposure"]], -kv[1]["n"])):
            md.append(f"| {target} | {TIER_LABEL[t['exposure']]} | {t['n']} | {t['fix']} | {t['n'] - t['fix']} | {t['worst']} |")
    md += ["", "## Worth knowing, with or without a CVE", ""]
    if eol:
        md += [f"- **End of support:** {e}" for e in eol]
    md += [f"- {n}" for n in notes] or ([] if eol else ["- Run `check.yml` first to include pending updates and outdated images."])
    md += ["", "## Coverage", "", f"Scanned {len(scanned)} target(s)."]
    if unscannable:
        md += ["", "Not scanned (no registry digest to look up):"] + [f"- {u['target']}: {u['ref']}" for u in unscannable]
    if errors:
        md += ["", "Scan errors:"] + [f"- {e}" for e in errors]
    md += ["", "Not covered: TrueNAS's own packages and Proxmox's kernel packages (not in Debian's security "
           "data). Read their release notes.", ""]
    with open(os.path.join(a.reports_dir, "cve-report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"scanned {len(scanned)} targets: {len(findings)} need attention, {lower} lower, "
          f"{len(errors)} error(s), {len(unscannable)} not scannable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
