# Patch management

Ansible that reports and applies updates across the homelab. One run of `check.yml` tells you
what is pending everywhere and writes a Markdown and JSON report. `apply.yml` patches, and only
when you confirm it.

| Target | Check | Apply |
|---|---|---|
| Debian, Ubuntu, Raspberry Pi OS | `apt-get -s dist-upgrade`, held packages, reboot marker | `apt dist-upgrade`, optional reboot |
| Proxmox VE host | same as Debian, plus `pveversion` | same; a reboot needs its own flag |
| Proxmox LXCs (incl. community-script ones) | `pct exec` into each running CT (Debian, Ubuntu, Alpine) | package upgrade in each CT, optional snapshot first |
| Docker | running containers, image vs registry digest | `docker compose pull` and `up -d` for listed projects |
| TrueNAS | `midclt update.check_available`, `zpool status -x` | none: update from the TrueNAS UI |

## Setup

```bash
cd patch-management/ansible
cp inventory/inventory.yml.example inventory/inventory.yml   # gitignored, add your hosts
ansible-galaxy collection install -r requirements.yml
```

Every SSH target uses a dedicated `patch` user with your key and sudo. Create it once:

```bash
ansible-playbook playbooks/bootstrap.yml -e ansible_user=<existing-user> --ask-pass --ask-become-pass
```

It uses `~/.ssh/id_ed25519.pub` (or `patch_user_public_key`). The account is key-only with a
locked password and gets passwordless sudo (`patch_user_sudo_nopasswd`), so anyone with your
SSH key can become root on these hosts: protect the key. Use `-e ansible_user=`, not `-u`: the inventory's
`ansible_user` overrides `-u`. Containers need `openssh-server` installed first. TrueNAS is
skipped: add the `patch` user in its UI (Credentials, Local Users, with your SSH public key
and sudo allowed) and enable the SSH service. Do not edit `/etc` there, it is reset on update.

Keep the real inventory, addresses and any vault file out of git: this repo is public.

On Proxmox, containers are patched through the host, so they need no SSH or inventory entry.
Tag a CT `nopatch` or list its VMID in `patch_lxc_skip` to leave it alone.

## Use

```bash
ansible-playbook playbooks/check.yml
# report: ../reports/patch-report.md and patch-report.json

ansible-playbook playbooks/apply.yml -e patch_confirm=true
ansible-playbook playbooks/apply.yml -e patch_confirm=true --limit vm-example -e patch_reboot=true
```

`apply.yml` handles one host at a time (`-e patch_serial=2` for more), stops a batch when a host
fails, patches a Proxmox host's containers before the host itself, and rewrites the report with
what was applied and what is still pending.

## Settings

Defaults live in `ansible/inventory/group_vars/all.yml`. Override them with `-e`, or as host
vars in the inventory. Group vars written in `inventory.yml` do not work: `group_vars/all.yml` wins
over them.

| Variable | Default | Meaning |
|---|---|---|
| `patch_confirm` | `false` | `apply.yml` refuses to run unless true |
| `patch_serial` | `1` | hosts patched at once (command line only) |
| `patch_reboot` | `false` | reboot when the host reports it needs one |
| `patch_reboot_proxmox` | `false` | also required to reboot a Proxmox host, which stops all guests |
| `patch_lxc_snapshot` | `false` | `pct snapshot pre-patch-<date>` before patching a CT |
| `patch_lxc_skip` | `[]` | VMIDs to skip |
| `patch_compose_projects` | `[]` | per host: compose directories to update on apply |
| `patch_docker_prune` | `false` | prune unused images after an apply |
| `patch_docker_skip_project_prefix` | `""` | hide compose projects with this prefix from the Docker report (`ix-` hides TrueNAS catalog apps) |

## CVE report

`playbooks/cve-scan.yml` looks for known vulnerabilities and writes `reports/cve-report.md` and
`.json`. It only reports; it changes nothing. Trivy runs on the machine you start Ansible from, so
the hosts do no scanning:

- SSH hosts and Proxmox containers hand over `/etc/os-release` and the dpkg package list
  (containers are read with `pct exec`). Trivy matches them against the distro security data.
- Docker hosts hand over the registry digest of each running image. Trivy downloads that exact
  image from the registry and scans it. The first run pulls many layers; later runs reuse them.
- Trivy is installed from a pinned, checksum-verified release into `~/.local/bin`. CISA's
  known-exploited list is fetched on every run.

The report lists CVEs at `patch_cve_min_cvss` (default 8.5) or higher, plus anything CISA lists
as exploited, sorted by exposure. Set exposure in `inventory.yml` (not in `group_vars/all.yml`,
which would override it):

```yaml
patch_cve_exposure:
  direct: [npmplus, immich, jellyfin] # port-forwarded to the home IP
  tunnel: [] # behind a Cloudflare Tunnel
patch_cve_exposed_hosts: [truenas-scale, pve3-ct102-docker-3] # host, or node-ctID-name
```

A second section lists things worth knowing without a CVE: pending updates, held packages,
reboots, outdated images, a TrueNAS update, an OS past its end of support. It reads the last
`check.yml` result, so run that first. Fixed and unfixed CVEs are both shown ("no fix yet").

To run it daily from a small VM later, copy the repo there, add the inventory and an SSH key,
and call `ansible-playbook playbooks/cve-scan.yml` from a systemd timer or cron job.

Not covered: TrueNAS's own packages and Proxmox's kernel packages, which are not in Debian's
security data. A CVSS score says how bad a flaw is in general, not whether your setup can be
hit, so treat the list as things to look at.

## Daily scanner

`playbooks/scanner.yml` creates a small container on a Proxmox node that runs `check.yml` and
`cve-scan.yml` every day (05:00 UTC, with a random delay of up to 10 minutes), writes metrics for
Prometheus, and serves the reports on port 8080 to your LAN. It never runs `apply.yml`.

```bash
ansible-playbook playbooks/scanner.yml
```

Needs in `inventory.yml` (see the example): `patch_scanner_ct_enabled: true`, an address and
gateway on one Proxmox host, and a host in the `scanner` group. The playbook creates the
container (2 vCPU, 4 GB RAM, 20 GB disk, unprivileged, Debian 13), installs the tools, copies
the project and your inventory into it, and adds the container's own SSH key to the `patch` user
on every host. Run it again to push a newer copy of the project. A first scan takes about 20
minutes (image downloads); later ones take a few minutes.

- **TrueNAS is a manual step.** The playbook prints the scanner's public key at the end. Add it to
  the TrueNAS `patch` user's SSH key field (one key per line).
- **Security.** The scanner's key gives passwordless root on every host, because `patch` has
  full sudo. Keep that container locked down: no inbound access except SSH from your admin
  machine, port 8080 and the metrics port from your LAN.
- Start a run by hand: `ssh root@<scanner> systemctl start patch-scan.service`; follow it with
  `journalctl -u patch-scan.service -f`.
- Optional: set `patch_scanner_healthcheck_url` to a healthchecks.io URL to get a ping when a
  run finishes and a failure ping when it does not.

### Dashboard and alerts

Metrics are written to the node exporter's textfile directory on the scanner. Add the scanner
to your Prometheus (replace the address):

```yaml
scrape_configs:
  - job_name: patch-scanner
    static_configs:
      - targets: ["<scanner-address>:9100"]
```

Import `grafana/patch-cve-overview.json` in Grafana (Dashboards, New, Import) and pick your
Prometheus data source. Rules in `grafana/patch-alerts.yml` can be added to Prometheus. The
dashboard has not been loaded into a Grafana yet, so expect to adjust a panel or two. The per-CVE
list stays in the report page (`cve-report.md`, `cve-report.json`); metrics only carry counts.

## Limits

- Held packages stay held. Kernel or firmware holds, such as the ones on the LLM host
  (`llm-server/docs/kernel-update.md`), show up in the "Held" column and are not upgraded.
- The reboot flag comes from `/var/run/reboot-required`. Minimal Debian and Proxmox installs
  may not create it, so a new kernel can be pending without the report saying so.
- Community-script LXCs often update their app with an interactive `update` command. That is not
  run; only the OS packages are. Check the app separately.
- Docker image status needs the buildx plugin and registry access, and is best effort. Images
  pinned by digest show `pinned` and are never reported as outdated. Compose projects with
  deliberate pins (such as the LLM host) should not be listed in `patch_compose_projects`.
- **Which Docker stacks `apply.yml` updates:** only the directories listed in a host's
  `patch_compose_projects` (`docker compose pull` and `up -d`). The default is none, so by
  default `apply.yml` updates no containers. On TrueNAS, list Dockge stack directories there
  (for example `/mnt/.ix-apps/app_mounts/dockge/stacks/<name>`). TrueNAS catalog apps (project
  `ix-<app>`) are shown in the report but never touched: update them from the Apps screen. Image status `unknown` means no registry digest could be compared (for example a
  locally built image or an unreachable registry).
- TrueNAS is never changed. Check the report, then update from the UI.
- The check logic is tested against stubbed command output. The apply paths have not been run on
  real hosts yet: try `--limit` on one low-risk host first.

## Checks

```bash
cd patch-management/ansible
ansible-playbook playbooks/check.yml --syntax-check
ansible-playbook playbooks/apply.yml --syntax-check
ansible-lint playbooks roles
```
