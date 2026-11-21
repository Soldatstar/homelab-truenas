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
