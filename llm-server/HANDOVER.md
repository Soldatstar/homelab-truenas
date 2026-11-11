# Handover: working on this from WSL

How to pick up the `llm-server/` setup in a fresh WSL (Ubuntu) shell. Everything here is run
**from WSL, with the repo in the Linux home directory**. Do not work from `/mnt/c/...`:
Ansible ignores `ansible.cfg` in world-writable directories, file modes are wrong, and
git sees spurious line-ending changes.

## What is running

| | |
|---|---|
| Host | `llmviktor`, 192.168.1.41 (Ubuntu 26.04, 2x Radeon AI PRO R9700, 128 GB RAM) |
| GPU model | Qwen3.8-27B, `mxfp4` (default) or `fp8`, one at a time; served as `qwen3.8-27b` / `claude-local` |
| CPU model | `qwen3.6-35b-a3b-cpu` (llama.cpp, system RAM), shown in Open WebUI only |
| Chat | Open WebUI, https://chat.viktornote.ch (Authentik login, signup closed) |
| API | https://llm.viktornote.ch (NPM Plus -> :8000, API key required, LAN only) |
| Dashboard | Grafana, http://192.168.1.41:3001 (admin + `vault_grafana_admin_password`) |
| Reverse proxy | NPM Plus on 192.168.1.10, configured by hand, not in this repo |

Architecture and details: [README.md](README.md). Open items: [NEXT-STEPS.md](NEXT-STEPS.md).

## 1. Set up WSL once

```bash
sudo apt update && sudo apt install -y git pipx openssh-client curl
pipx install --include-deps ansible      # or: pipx install ansible-core
pipx install ansible-lint yamllint       # optional, for checks
pipx ensurepath

git config --global user.name  "soldatstar"
git config --global user.email "<your github email>"
git clone https://github.com/Soldatstar/homelab-truenas.git ~/homelab-truenas
cd ~/homelab-truenas/llm-server/ansible
ansible-galaxy collection install -r requirements.yml
```

The Windows checkout under `Documents\vscode\homelab-truenas` can be archived or deleted
once the items in section 2 are copied over. Keep one working copy only.

## 2. Things that are NOT in git (copy them over)

| What | Where it lives now | Where it goes |
|---|---|---|
| **Ansible vault** (all secrets, encrypted) | Windows checkout: `llm-server/ansible/inventory/group_vars/llm/vault.yml` | same path in the WSL clone (gitignored) |
| **Vault password** | your password manager (not stored anywhere on disk) | typed at `--ask-vault-pass` |
| **SSH key** that is on the host | `~/.ssh` in WSL if `ssh-copy-id` was done; otherwise the Windows `C:\Users\Viktor\.ssh` | `~/.ssh/` in WSL, `chmod 600` the private key |
| k3s Terraform variables | `k3s-cluster/terraform/terraform.tfvars` (gitignored) | same path, only if you work on `k3s-cluster/` |

Copy from the Windows checkout (adjust the source path if it moved):

```bash
SRC=/mnt/c/Users/Viktor/Documents/vscode/homelab-truenas
cp "$SRC/llm-server/ansible/inventory/group_vars/llm/vault.yml" \
   ~/homelab-truenas/llm-server/ansible/inventory/group_vars/llm/vault.yml
cp "$SRC/k3s-cluster/terraform/terraform.tfvars" ~/homelab-truenas/k3s-cluster/terraform/   # optional
# SSH key, only if WSL has none yet:
mkdir -p ~/.ssh && cp /mnt/c/Users/Viktor/.ssh/id_ed25519* ~/.ssh/ && chmod 600 ~/.ssh/id_ed25519
```

Check the copy worked (the vault must still be encrypted, first line `$ANSIBLE_VAULT;1.1;AES256`):

```bash
cd ~/homelab-truenas/llm-server/ansible
head -1 inventory/group_vars/llm/vault.yml
ansible llm -m ping                    # SSH works
ansible-vault view inventory/group_vars/llm/vault.yml   # password works
```

Never commit `vault.yml` in plaintext; `.gitignore` excludes it and `site.yml` refuses to run
if it is not encrypted. This repo is **public**: no keys, passwords or tokens in any tracked
file (`vault.yml.example` has placeholders only).

## 3. Daily commands

All from `~/homelab-truenas/llm-server/ansible`. Add `--ask-become-pass --ask-vault-pass`
to every `ansible-playbook` call below (or run `playbooks/sudo-nopasswd.yml` once).

| Task | Command |
|---|---|
| Full deploy | `ansible-playbook playbooks/site.yml` |
| Dry run | `... site.yml --check --diff` |
| Only the engine | `... site.yml --tags engine` |
| Only Open WebUI | `... site.yml --tags webui` |
| Only the CPU model | `... site.yml --tags cpu` (add `webui` if the connection changed) |
| Dashboard | `... site.yml --tags dashboard` |
| Switch GPU model | `... site.yml --tags models,engine -e llm_model=fp8` (or `mxfp4`) |
| Switch context profile | `... site.yml --tags engine -e llm_profile=long` |
| Verify everything | `ansible-playbook playbooks/smoke-test.yml -e llm_model=fp8` (use the loaded model) |
| Edit secrets | `ansible-vault edit inventory/group_vars/llm/vault.yml` |
| Lint | `ansible-lint playbooks roles` and `yamllint .` |

Tags are defined in `playbooks/site.yml`. On the host: `docker logs -f vllm-radiance`,
`llm-gpu-stats`, `sudo iptables -S LLM-INGRESS`. More in the README's Operations table and
[docs/troubleshooting.md](docs/troubleshooting.md).

Claude Code against the local model (from WSL or any Linux box): `scripts/claude-local.sh`.
It asks for `vault_llm_api_key` once per run, or reads it from `~/.config/claude-local/key`.

## 4. Gotchas learned the hard way

- **The API key is `vault_llm_api_key`**, not the Open WebUI secret. A 401 from
  `llm.viktornote.ch` almost always means the wrong one.
- **Switching `llm_model` needs `-e llm_model=...` on the smoke test too**, otherwise it
  checks for the wrong third served name.
- **Only one GPU model is loaded.** Switching restarts the engine; Open WebUI and Claude
  Code are down for the load time (minutes with warm caches).
- **The `llm_dashboard` KV-cache panel** should stay below about 70% in normal use; FP8 has a
  smaller pool than MXFP4. If preemptions climb, use the `chat` MXFP4 model.
- **`ENABLE_PERSISTENT_CONFIG=false`** in Open WebUI: settings from the template win on every
  restart; changes in the admin UI for those same settings are lost.
- **Hidden models** (the unlabeled duplicate names) are not listed by Open WebUI; the smoke
  test accepts any served name for that reason.
- **Kernel and firmware are held on purpose.** Do not `apt upgrade` them casually:
  [docs/kernel-update.md](docs/kernel-update.md).
- **Nothing on the host is configured by hand** except the NPM Plus entries and the Authentik
  application. If you change something by hand on the host, put it in a role afterwards.
- **vllm-radiance is unmaintained upstream.** The image is pinned by digest on purpose; see
  the comment at the top of `inventory/group_vars/llm/images.yml` before bumping it.

## 5. Git conventions

- Branch `main`, push straight to `origin` (GitHub, public).
- Lowercase, imperative-ish commit subjects without a prefix, e.g. `adds llm_dashboard role`.
- **No `Co-Authored-By` trailers** in commits to this repo.
- `.gitattributes` forces LF line endings; `*.ps1` stays CRLF. Scripts keep their executable bit.
- Stale local branch `backup/pre-trailer-removal` holds the pre-rewrite history; delete it
  when you no longer need it (`git branch -D backup/pre-trailer-removal`).

## 6. Using Claude Code in WSL on this repo

Start `claude` in `~/homelab-truenas`. The repo-level [CLAUDE.md](../CLAUDE.md) gives it the
layout, commands and rules above. Sessions from the Windows checkout are stored under
`C:\Users\Viktor\.claude\projects\...` and are not visible from WSL; the written docs in this
folder are the source of truth, not that history.
