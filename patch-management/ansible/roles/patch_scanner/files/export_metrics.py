#!/usr/bin/env python3
"""Turn the last patch and CVE reports into Prometheus text metrics (node exporter textfile)."""
import json
import os
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), os.path.getmtime(path)
    except (OSError, ValueError):
        return None, None


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def main(reports, out):
    cve, cve_t = load(os.path.join(reports, "cve-report.json"))
    pat, pat_t = load(os.path.join(reports, "patch-report.json"))
    lines = []

    def metric(name, help_, kind="gauge"):
        lines.extend([f"# HELP {name} {help_}", f"# TYPE {name} {kind}"])

    def add(name, value, **labels):
        lab = ",".join(f'{k}="{esc(v)}"' for k, v in labels.items())
        lines.append(f"{name}{{{lab}}} {value}" if lab else f"{name} {value}")

    metric("patch_report_timestamp_seconds", "When each report file was last written")
    for kind, t in (("cve", cve_t), ("patch", pat_t)):
        if t:
            add("patch_report_timestamp_seconds", int(t), report=kind)

    if cve:
        metric("patch_cve_findings", "CVEs needing attention, per CVE and target, by exposure, fix and known-exploited")
        counts = {}
        for x in cve["attention"]:
            k = (x["exposure"], "yes" if x["fixes"] else "no", "yes" if x["kev"] else "no")
            counts[k] = counts.get(k, 0) + 1
        for exp in ("direct", "tunnel", "internal"):
            for fix in ("yes", "no"):
                for kev in ("yes", "no"):
                    add("patch_cve_findings", counts.get((exp, fix, kev), 0), exposure=exp, fix=fix, exploited=kev)
        metric("patch_cve_rated_lower_by_distro", "CVEs at the threshold that the distro rates lower (not listed)")
        add("patch_cve_rated_lower_by_distro", len(cve.get("rated_lower_by_distro", [])))
        metric("patch_cve_scan_errors", "Targets that could not be scanned")
        add("patch_cve_scan_errors", len(cve["errors"]))
        metric("patch_cve_targets_scanned", "Hosts, containers and images scanned")
        add("patch_cve_targets_scanned", len(cve["scanned"]))
        metric("patch_cve_end_of_support", "Targets whose base OS is past end of support")
        add("patch_cve_end_of_support", len(cve["end_of_support"]))
        metric("patch_cve_kev_loaded", "1 if the CISA known-exploited list was downloaded for this scan")
        add("patch_cve_kev_loaded", 1 if cve["kev_loaded"] else 0)

    if pat:
        metric("patch_updates_pending", "Package updates waiting, per host or container")
        metric("patch_security_updates_pending", "Of those, marked as security updates")
        metric("patch_reboot_required", "1 if the host says it needs a reboot")
        metric("patch_images", "Running images by status against their registry tag")
        metric("patch_truenas_update_available", "1 if TrueNAS offers a newer version")
        for h in pat["hosts"]:
            apt = h.get("apt")
            if apt:
                add("patch_updates_pending", len(apt["pending"]), host=h["name"])
                add("patch_security_updates_pending", len(apt["security"]), host=h["name"])
                add("patch_reboot_required", 1 if apt["reboot_required"] else 0, host=h["name"])
            for c in (h.get("lxc") or {}).get("containers", []):
                who = f"{h['name']}/ct{c['vmid']}-{c['name']}"
                add("patch_updates_pending", len(c["pending"]), host=who)
                add("patch_security_updates_pending", len(c["security"]), host=who)
            dk = h.get("docker")
            if dk:
                by = {}
                for i in dk["images"]:
                    by[i["status"]] = by.get(i["status"], 0) + 1
                for status in ("current", "outdated", "unknown", "pinned"):
                    add("patch_images", by.get(status, 0), host=h["name"], status=status)
            tn = h.get("truenas")
            if tn:
                add("patch_truenas_update_available", 1 if tn["update_status"] == "AVAILABLE" else 0, host=h["name"])

    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, out)  # the exporter never sees a half-written file
    print(f"wrote {len(lines)} lines to {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
