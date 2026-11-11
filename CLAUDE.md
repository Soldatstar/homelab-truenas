# Repo notes for Claude Code

Public GitHub repo (`Soldatstar/homelab-truenas`). Never put secrets, keys or tokens in tracked
files. Work from WSL with the repo in `~/homelab-truenas`, not under `/mnt/c`.

## Layout

- `llm-server/`: Ansible for the local LLM host `llmviktor` (192.168.1.41). Start with
  `llm-server/HANDOVER.md` (setup, secrets, commands, gotchas), then `README.md`,
  `NEXT-STEPS.md`, `VERSIONS.md`.
- `k3s-cluster/`: Terraform + Ansible for a k3s cluster. `terraform.tfvars` is gitignored.
- Top-level `README.md`: TrueNAS notes, unrelated to the LLM host.

## Rules

- Commit messages: lowercase, short, no prefix (`adds llm_dashboard role`). **No `Co-Authored-By`
  trailer**, even if tooling suggests one.
- Do not push, or run playbooks against the host, without being asked. Playbooks need the vault
  password and sudo password; ask the user to run them, or give the exact command.
- `vault.yml` is encrypted and gitignored; never print its contents. Only `vault.yml.example`
  is tracked.
- Everything on the host is configured through roles. If a fix is made by hand, add it to a role.
- Image digests, model revisions and the pinned vllm-radiance build are deliberate. Follow the
  procedure at the top of `llm-server/ansible/inventory/group_vars/llm/images.yml` to change them.
- Kernel and firmware packages are held on purpose (`llm-server/docs/kernel-update.md`).
- Keep docs in step with changes: tunables in `group_vars/llm/main.yml` are documented in
  `llm-server/README.md`; update `VERSIONS.md` when pins change.

## Checks (from `llm-server/ansible`)

```bash
ansible-playbook playbooks/site.yml --syntax-check
ansible-lint playbooks roles        # production profile
yamllint .
```

Verify a deployment with `playbooks/smoke-test.yml` (add `-e llm_model=fp8` when FP8 is loaded).
