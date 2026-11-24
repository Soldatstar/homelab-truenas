#!/usr/bin/env python3
"""Small control page for apply.yml: pick targets, review the plan, confirm, watch the log.

Runs on the scanner, bound to localhost; nginx adds TLS, the LAN allow list and the login.
Design rules:
  * The browser only ever sends target ids. The commands are built here, from an allow list that
    is derived from the last reports. Nothing the browser sends reaches a shell.
  * Every change needs two steps (plan, then confirm) and a CSRF token.
  * One job at a time. A job never reboots anything. It stops at the first failed target.
  * Proxmox nodes are never part of a bulk selection: one node per plan.
  * After a job the full check runs again so reports and dashboard show the new state.
"""
import argparse
import fcntl
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CFG = {}
PLANS = {}  # plan id -> {"ids": [...], "created": float}
RUN_LOCK = threading.Lock()
DIR_RE = re.compile(r"^/[A-Za-z0-9._/@+-]+$")
CSRF_TTL = 1800
PLAN_TTL = 600


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- what can be patched

def offered():
    """Return {id: item} for everything the page may patch, from the latest reports."""
    pat = load(os.path.join(CFG["reports"], "patch-report.json"), {})
    cve = load(os.path.join(CFG["reports"], "cve-report.json"), {})
    rows = [r for r in cve.get("attention", []) if r.get("fixes")]  # fixable only
    items = {}

    def fixable(pred):
        hit = [r for r in rows if pred(r["target"])]
        return len(hit), sum(1 for r in hit if r.get("kev"))

    for h in pat.get("hosts", []):
        name, apt = h["name"], h.get("apt")
        if apt:
            node = bool(apt.get("proxmox"))
            n, kev = fixable(lambda t, name=name: t == name)
            items[("node:" if node else "host:") + name] = {
                "kind": "node" if node else "host", "label": name, "scope": "host", "limit": name,
                "pending": len(apt["pending"]), "security": len(apt["security"]),
                "critical": n, "kev": kev, "reboot": bool(apt.get("reboot_required")),
                "held": apt.get("held", []), "keys": [name],
                "what": "OS packages" + (" of the Proxmox node (services restart, no reboot)" if node else ""),
            }
        for c in (h.get("lxc") or {}).get("containers", []):
            if c.get("probe_failed"):
                continue
            tgt = f"{name}-ct{c['vmid']}-{c['name']}"
            n, kev = fixable(lambda t, tgt=tgt: t == tgt)
            items[f"lxc:{name}:{c['vmid']}"] = {
                "kind": "lxc", "label": f"CT {c['vmid']} {c['name']} (on {name})", "scope": "lxc",
                "limit": name, "lxc_only": [int(c["vmid"])], "pending": len(c["pending"]),
                "security": len(c["security"]), "critical": n, "kev": kev, "reboot": False, "held": [],
                "keys": [f"{name}/ct{c['vmid']}-{c['name']}"], "self": c["name"] == socket.gethostname(),
                "what": "OS packages inside the container",
            }
    for path in sorted(os.listdir(os.path.join(CFG["workdir"], "images"))) if os.path.isdir(
            os.path.join(CFG["workdir"], "images")) else []:
        host = path[:-5]
        if host in CFG["no_stacks"]:
            continue
        stacks = {}
        for c in load(os.path.join(CFG["workdir"], "images", path), []):
            d, proj = c.get("workdir", ""), c.get("project", "")
            if not d or not DIR_RE.match(d) or proj.startswith(CFG["skip_prefix"]):
                continue
            s = stacks.setdefault(d, {"project": proj, "containers": []})
            s["containers"].append(f"{host}:{c['name']}")
        for d, s in stacks.items():
            mine = set(s["containers"])
            hit = [r for r in rows if r["kind"] == "image" and mine & set(re.findall(r"([\w.-]+:[\w.-]+)", r["target"]))]
            items[f"stack:{host}:{d}"] = {
                "kind": "stack", "label": f"{s['project'] or d} (on {host})", "scope": "stacks", "limit": host,
                "dirs": [d], "portainer": d.startswith("/data/compose/"), "pending": 0, "security": 0, "critical": len(hit),
                "kev": sum(1 for r in hit if r.get("kev")), "reboot": False, "held": [], "keys": [],
                "what": f"pull images and restart the stack in {d}",
            }
    return items


def commands(item):
    """The exact ansible-playbook call for one target. Built only from validated data."""
    cmd = ["ansible-playbook", "playbooks/apply.yml", "-e", "patch_confirm=true", "-e", "patch_reboot=false",
           "-e", f"patch_reports_dir={CFG['reports']}", "-e", f"patch_scope={item['scope']}",
           "--limit", item["limit"]]
    if item["kind"] == "lxc":
        cmd += ["-e", json.dumps({"patch_lxc_only": item["lxc_only"]})]
    if item["kind"] == "stack":
        cmd += ["-e", json.dumps({"patch_compose_projects": item["dirs"]})]
    return cmd


ORDER = {"lxc": 0, "host": 1, "stack": 2, "node": 3}


# ---------------------------------------------------------------- security helpers

def secret():
    path = os.path.join(CFG["state"], "secret")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return open(path, encoding="utf-8").read().strip().encode()


def make_csrf():
    ts = str(int(time.time()))
    return ts + "." + hmac.new(secret(), ts.encode(), hashlib.sha256).hexdigest()


def check_csrf(tok):
    try:
        ts, sig = tok.split(".", 1)
        good = hmac.new(secret(), ts.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good) and 0 <= time.time() - int(ts) <= CSRF_TTL
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------- jobs

def run_job(job_id, ids, items):
    log_path = os.path.join(CFG["state"], "jobs", job_id + ".log")
    meta_path = os.path.join(CFG["state"], "jobs", job_id + ".json")
    lock_file = open(os.path.join(CFG["state"], "job.lock"), "w")
    meta = load(meta_path, {})

    def save(**kw):
        meta.update(kw)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        with open(log_path, "w", encoding="utf-8") as log:
            ok = True
            for i in ids:
                item = items[i]
                log.write(f"\n===== {item['label']}: {item['what']} =====\n")
                log.write("$ " + " ".join(commands(item)) + "\n")
                log.flush()
                save(current=item["label"])
                rc = subprocess.run(commands(item), cwd=CFG["ansible"], stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, check=False).returncode
                if rc != 0:
                    ok = False
                    log.write(f"\n!!! {item['label']} failed (exit {rc}). Remaining targets were not touched.\n")
                    break
            log.write("\n===== refreshing the patch report =====\n")
            log.flush()
            subprocess.run(["ansible-playbook", "playbooks/check.yml", "-e", f"patch_reports_dir={CFG['reports']}"],
                           cwd=CFG["ansible"], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=False)
            subprocess.run(["python3", CFG["exporter"], CFG["reports"], CFG["prom"]], stdout=log,
                           stderr=subprocess.STDOUT, check=False)
        save(status="done" if ok else "failed", finished=time.time(), current="")
    except Exception as e:  # never leave a job "running" forever
        save(status="failed", error=str(e), finished=time.time())
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
        RUN_LOCK.release()


def run_scan(job_id):
    """Run the same script the daily timer runs: patch check, CVE scan, metrics. Read-only.
    The script takes the shared lock itself, so it also waits for a scheduled run."""
    log_path = os.path.join(CFG["state"], "jobs", job_id + ".log")
    meta_path = os.path.join(CFG["state"], "jobs", job_id + ".json")
    meta = load(meta_path, {})

    def save(**kw):
        meta.update(kw)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

    try:
        with open(log_path, "w", encoding="utf-8") as log:
            log.write("$ " + CFG["scan_cmd"] + "\n")
            log.flush()
            save(current="patch check, CVE scan and metrics (takes a few minutes)")
            rc = subprocess.run([CFG["scan_cmd"]], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                check=False).returncode
            if rc != 0:
                log.write(f"\n!!! The scan exited with {rc}. An unreachable host or a failed image scan also does this; see above.\n")
        save(status="done" if rc == 0 else "failed", finished=time.time(), current="")
    except Exception as e:
        save(status="failed", error=str(e), finished=time.time())
    finally:
        RUN_LOCK.release()


def ago(path):
    try:
        secs = int(time.time() - os.path.getmtime(path))
    except OSError:
        return "never"
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{secs // 60} minutes ago"
    if secs < 172800:
        return f"{secs // 3600} hours ago"
    return f"{secs // 86400} days ago"


def busy():
    for name in os.listdir(os.path.join(CFG["state"], "jobs")):
        if name.endswith(".json") and load(os.path.join(CFG["state"], "jobs", name), {}).get("status") == "running":
            return True
    return False


# ---------------------------------------------------------------- pages

CSS = """
:root{--bg:#fff;--fg:#1d2330;--mut:#667085;--line:#e2e6ee;--card:#f6f8fb;--acc:#2f6fed;--red:#c62828;--org:#b95c00;--grn:#1b7f3a}
@media(prefers-color-scheme:dark){:root{--bg:#111318;--fg:#e6e9ef;--mut:#98a2b3;--line:#2a2f3a;--card:#1a1e27;--acc:#6b9bff;--red:#ff6b6b;--org:#ffa94d;--grn:#51cf66}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}
p{margin:6px 0}.mut{color:var(--mut)}table{width:100%;border-collapse:collapse}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}td.n,th.n{text-align:right}tr.focus{background:var(--card);outline:2px solid var(--acc)}
.red{color:var(--red);font-weight:600}.org{color:var(--org)}.grn{color:var(--grn)}code,pre{font:13px ui-monospace,monospace}
pre{background:var(--card);border:1px solid var(--line);padding:10px;overflow:auto;white-space:pre-wrap;border-radius:6px}
button,.btn{font:inherit;padding:8px 14px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer;text-decoration:none;display:inline-block}
button.go{background:var(--acc);border-color:var(--acc);color:#fff}button.warn{background:var(--red);border-color:var(--red);color:#fff}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.box{border:1px solid var(--line);background:var(--card);padding:10px 14px;border-radius:8px;margin:12px 0}
"""


def page(title, body, refresh=0):
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"{meta}<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>")


def e(x):
    return html.escape(str(x))


def index_page(focus="", preset=""):
    items = offered()
    csrf = make_csrf()
    jobs = sorted((load(os.path.join(CFG["state"], "jobs", n), {}) for n in os.listdir(os.path.join(CFG["state"], "jobs"))
                   if n.endswith(".json")), key=lambda j: j.get("created", 0), reverse=True)[:5]
    pre = {i for i, it in items.items()
           if preset == "critical" and it["critical"] and it["kind"] != "node" and not it.get("portainer") and not it.get("self")}
    body = ['<h1>Patch control</h1><p class="mut">Updates OS packages and Docker stacks. Nothing reboots, and nothing runs until you have reviewed a plan and confirmed it.</p>']
    if busy():
        body.append('<div class="box red">A job is running. Open it below; new jobs wait until it ends.</div>')
    if not items:
        body.append('<div class="box">No targets yet: the daily scan has not produced a report.</div>')
    body.append(f'<form method="post" action="/scan" class="bar"><input type="hidden" name="csrf" value="{e(csrf)}">'
                f'<button type="submit">Scan now</button><span class="mut" style="align-self:center">Last scan: '
                f'{e(ago(os.path.join(CFG["reports"], "cve-report.json")))}. Checks pending updates and CVEs; changes nothing.</span></form>')
    body.append(f'<form method="post" action="/plan"><input type="hidden" name="csrf" value="{e(csrf)}">')
    body.append('<div class="bar"><button class="go" type="submit">Review selected</button>'
                '<a class="btn" href="/?preset=critical">Select all with fixable critical CVEs</a>'
                '<a class="btn" href="/">Clear</a></div>')
    for kind, title in (("host", "Hosts"), ("lxc", "Containers (Proxmox)"), ("stack", "Docker stacks"), ("node", "Proxmox nodes (one at a time)")):
        rows = sorted([(i, it) for i, it in items.items() if it["kind"] == kind],
                      key=lambda kv: (-kv[1]["kev"], -kv[1]["critical"], -kv[1]["security"], kv[1]["label"]))
        if not rows:
            continue
        body.append(f"<h2>{title}</h2><table><tr><th></th><th>Target</th><th class='n'>Pending</th><th class='n'>Security</th>"
                    "<th class='n'>Fixable critical CVEs</th><th>Notes</th></tr>")
        for i, it in rows:
            cls = ' class="focus"' if focus and focus in it["keys"] else ""
            crit = f'<span class="red">{it["critical"]}</span>' if it["critical"] else "0"
            if it["kev"]:
                crit += f' <span class="red">({it["kev"]} exploited)</span>'
            notes = []
            if it["reboot"]:
                notes.append("reboot needed afterwards (not done here)")
            if it["held"]:
                notes.append("held, will not update: " + ", ".join(it["held"]))
            if kind == "stack":
                notes.append(it["what"])
            if it.get("self"):
                notes.append("this is the scanner itself: the page may restart during the update")
            if it.get("portainer"):
                notes.append("Portainer stack: variables set in Portainer may be missing if recreated here. Prefer Portainer's own Update")
            body.append(f'<tr{cls}><td><input type="checkbox" name="id" value="{e(i)}" {"checked" if i in pre else ""}></td>'
                        f'<td>{e(it["label"])}</td><td class="n">{it["pending"]}</td><td class="n">{it["security"]}</td>'
                        f'<td class="n">{crit}</td><td class="mut">{e("; ".join(notes))}</td></tr>')
        body.append("</table>")
    body.append("</form>")
    if jobs:
        body.append("<h2>Recent jobs</h2><table><tr><th>Started</th><th>Status</th><th>Targets</th></tr>")
        for j in jobs:
            st = j.get("status", "?")
            c = "grn" if st == "done" else ("red" if st == "failed" else "org")
            body.append(f'<tr><td><a href="/job/{e(j["id"])}">{time.strftime("%Y-%m-%d %H:%M", time.localtime(j.get("created", 0)))}</a></td>'
                        f'<td class="{c}">{e(st)}</td><td>{e(", ".join(j.get("labels", [])))}</td></tr>')
        body.append("</table>")
    body.append('<p class="mut" style="margin-top:28px">"Fixable critical CVEs" counts findings from the last CVE scan that have a fixed version. '
                'Container image CVEs are only fixed by updating that stack. Data is as old as the last daily scan.</p>')
    return page("Patch control", "".join(body))


def plan_page(ids, items):
    chosen = [items[i] for i in sorted(ids, key=lambda i: ORDER[items[i]["kind"]])]
    pid = secrets.token_urlsafe(16)
    PLANS[pid] = {"ids": sorted(ids, key=lambda i: ORDER[items[i]["kind"]]), "created": time.time()}
    body = ['<h1>Review the plan</h1><p>These targets will be updated in this order, one at a time. '
            'If one fails, the rest are skipped. <b>No reboots.</b> Afterwards the patch report is refreshed.</p>']
    body.append("<table><tr><th>#</th><th>Target</th><th>What happens</th></tr>")
    for n, it in enumerate(chosen, 1):
        warn = ""
        if it["kind"] == "node":
            warn = ' <span class="red">Proxmox node: services on it restart. Check quorum and that no other node is down.</span>'
        if it.get("self"):
            warn = ' <span class="red">This is the scanner itself. The page and the job can be interrupted; run it alone and check the result.</span>'
        if it.get("portainer"):
            warn = ' <span class="red">Managed by Portainer: environment variables kept in Portainer may be lost when the stack is recreated here. Update it in Portainer if you are unsure.</span>'
        body.append(f"<tr><td>{n}</td><td>{e(it['label'])}</td><td>{e(it['what'])}{warn}</td></tr>")
    body.append("</table><h2>Commands</h2><pre>" + e("\n".join(" ".join(commands(it)) for it in chosen)) + "</pre>")
    body.append(f'<form method="post" action="/run" class="bar"><input type="hidden" name="csrf" value="{e(make_csrf())}">'
                f'<input type="hidden" name="plan" value="{e(pid)}"><button class="warn" type="submit">Patch now</button>'
                '<a class="btn" href="/">Cancel</a></form>')
    return page("Review the plan", "".join(body))


def job_page(job_id):
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        return None
    meta = load(os.path.join(CFG["state"], "jobs", job_id + ".json"), None)
    if not meta:
        return None
    try:
        with open(os.path.join(CFG["state"], "jobs", job_id + ".log"), encoding="utf-8", errors="replace") as f:
            tail = "".join(f.readlines()[-400:])
    except OSError:
        tail = ""
    st = meta.get("status", "?")
    c = "grn" if st == "done" else ("red" if st == "failed" else "org")
    body = [f'<h1>Job <span class="{c}">{e(st)}</span></h1><p class="mut">{e(", ".join(meta.get("labels", [])))}</p>']
    if st == "running":
        body.append(f'<p>Now: {e(meta.get("current", ""))}. This page refreshes every 5 seconds.</p>')
    body.append(f"<pre>{e(tail) or 'Waiting for output...'}</pre><p><a class='btn' href='/'>Back</a></p>")
    return page("Patch job", "".join(body), refresh=5 if st == "running" else 0)


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "patch-control"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, where):
        self.send(303, "", extra={"Location": where})

    def same_origin(self):
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        host = self.headers.get("Host", "")
        return not origin or urlparse(origin).netloc == host

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            self.send(200, index_page(q.get("focus", [""])[0][:80], q.get("preset", [""])[0]))
        elif u.path.startswith("/job/"):
            p = job_page(u.path[5:])
            self.send(200, p) if p else self.send(404, page("Not found", "<p>No such job.</p>"))
        else:
            self.send(404, page("Not found", "<p>Not found.</p>"))

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536 or "application/x-www-form-urlencoded" not in (self.headers.get("Content-Type") or ""):
            return None
        return parse_qs(self.rfile.read(n).decode("utf-8", "replace"))

    def do_POST(self):
        f = self.form()
        if f is None or not self.same_origin() or not check_csrf((f.get("csrf") or [""])[0]):
            return self.send(403, page("Refused", "<p>This form has expired or came from somewhere else. "
                                                  "<a href='/'>Start again</a>.</p>"))
        if self.path == "/scan":
            if busy() or not RUN_LOCK.acquire(blocking=False):
                return self.send(409, page("Busy", "<p>A job is already running. <a href='/'>Back</a></p>"))
            job_id = secrets.token_hex(6)
            with open(os.path.join(CFG["state"], "jobs", job_id + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"id": job_id, "created": time.time(), "status": "running", "kind": "scan",
                           "labels": ["Scan (patch check + CVE scan)"]}, fh)
            threading.Thread(target=run_scan, args=(job_id,), daemon=True).start()
            return self.redirect(f"/job/{job_id}")
        items = offered()
        if self.path == "/plan":
            ids = list(dict.fromkeys(f.get("id", [])))
            bad = [i for i in ids if i not in items]
            if not ids or bad:
                return self.send(400, page("Nothing to do", "<p>Select at least one target that is still on the list. "
                                                            "<a href='/'>Back</a></p>"))
            if sum(1 for i in ids if items[i]["kind"] == "node") > 1:
                return self.send(400, page("One node at a time", "<p>Select only one Proxmox node per plan. <a href='/'>Back</a></p>"))
            return self.send(200, plan_page(ids, items))
        if self.path == "/run":
            pid = (f.get("plan") or [""])[0]
            for k in [k for k, v in PLANS.items() if time.time() - v["created"] > PLAN_TTL]:
                PLANS.pop(k, None)
            plan = PLANS.pop(pid, None)
            if not plan or any(i not in items for i in plan["ids"]):
                return self.send(400, page("Plan expired", "<p>The plan is older than 10 minutes or the targets changed. <a href='/'>Review again</a>.</p>"))
            if busy() or not RUN_LOCK.acquire(blocking=False):
                return self.send(409, page("Busy", "<p>A job is already running. <a href='/'>Back</a></p>"))
            job_id = secrets.token_hex(6)
            with open(os.path.join(CFG["state"], "jobs", job_id + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"id": job_id, "created": time.time(), "status": "running", "ids": plan["ids"],
                           "labels": [items[i]["label"] for i in plan["ids"]]}, fh)
            threading.Thread(target=run_job, args=(job_id, plan["ids"], items), daemon=True).start()
            return self.redirect(f"/job/{job_id}")
        self.send(404, page("Not found", "<p>Not found.</p>"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--reports", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--prom", required=True)
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--no-stacks", default="", help="comma separated hosts whose stacks must not be offered")
    ap.add_argument("--scan-cmd", default="/usr/local/bin/patch-scan-daily", help="script run by Scan now")
    ap.add_argument("--skip-prefix", default="ix-", help="compose projects with this prefix are TrueNAS apps")
    a = ap.parse_args()
    CFG.update(project=a.project, ansible=os.path.join(a.project, "ansible"), reports=a.reports, workdir=a.workdir,
               state=a.state, prom=a.prom, exporter=os.path.join(a.project, "export_metrics.py"),
               no_stacks=set(filter(None, a.no_stacks.split(","))), scan_cmd=a.scan_cmd, skip_prefix=a.skip_prefix or "\0")
    os.makedirs(os.path.join(a.state, "jobs"), mode=0o700, exist_ok=True)
    # a job left "running" by a restart is not running any more
    for n in os.listdir(os.path.join(a.state, "jobs")):
        p = os.path.join(a.state, "jobs", n)
        m = load(p, None) if n.endswith(".json") else None
        if m and m.get("status") == "running":
            m.update(status="failed", error="service restarted")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(m, fh)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
