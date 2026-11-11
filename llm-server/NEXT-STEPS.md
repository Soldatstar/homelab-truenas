# Next steps

State on 2026-11-11: **deployed and in use.** The MXFP4 and FP8 models both load and answer,
Open WebUI works behind NPM Plus with Authentik login, Claude Code connects through
`llm.viktornote.ch`, and the CPU model and Grafana dashboard are running. The smoke test
passed for MXFP4; for FP8 only the Open WebUI model-list check failed, because the check was
too strict (fixed in `3c31140`), so a clean FP8 rerun is the first item below.

Setup on a new machine, secrets and daily commands: [HANDOVER.md](HANDOVER.md).

## Do next

- [ ] Rerun the smoke test on FP8 and confirm it is clean (CPU model, signup closed, firewall):
      `ansible-playbook playbooks/smoke-test.yml --ask-become-pass --ask-vault-pass -e llm_model=fp8`
- [ ] Decide MXFP4 vs FP8 as the default (`llm_model` in `group_vars/llm/main.yml`). Judge on
      your usual prompts: speed and answer quality. Watch the dashboard's KV-cache panel
      during a long chat; keep it under about 70%. Record the verdict in `VERSIONS.md`.
- [ ] Push the local commits (`git status` shows how many are ahead of `origin/main`).
- [ ] Move day-to-day work to the WSL clone (HANDOVER.md, sections 1 and 2), then retire the
      Windows checkout.

## Verify once, if not done yet

- [ ] Reboot the host and rerun the smoke test, to prove the firewall unit and all containers
      come back by themselves. Check `sudo iptables -S LLM-INGRESS` lists 192.168.1.0/24 and
      that a host outside it (phone on mobile data, another VLAN) cannot reach :8000 or :3000.
- [ ] Check both GPU fans spin under load (open upstream report on kernel 7.0), via
      `llm-gpu-stats` or the dashboard.
- [ ] Baseline numbers: `python3 scripts/bench.py --base-url https://llm.viktornote.ch --model qwen3.8-27b`
      (upstream reference: about 53 tok/s single, 102 tok/s at two streams). Note them in
      `VERSIONS.md`, for both models.
- [ ] Update the "Not verified" list in [VERSIONS.md](VERSIONS.md) with what is confirmed.

## Reverse proxy (NPM Plus, by hand)

Configured. For reference or rebuilding: `chat.viktornote.ch` -> `http://192.168.1.41:3000`
with websockets; `llm.viktornote.ch` -> `http://192.168.1.41:8000`, LAN-only access list,
`/metrics` and `/docs` blocked. Snippets and Authentik notes:
[docs/reverse-proxy.md](docs/reverse-proxy.md).

## Later, optional

- [ ] Send Open WebUI background jobs to the CPU model (`llm_cpu_use_for_tasks: true`): frees GPU
      sequences, slightly weaker search queries.
- [ ] Passwordless sudo for Ansible: `playbooks/sudo-nopasswd.yml` (opt-in, read the header).
- [ ] Try the untested `long` (262,144 x 4) or `coding` (262,144 x 2) profile with
      `-e llm_profile=long`, and record in `VERSIONS.md` whether it starts.
- [ ] Narrow `llm_allowed_sources` to the proxy (`192.168.1.10`) if only the proxy should
      reach the services; required before enabling Authentik trusted-header SSO.
- [ ] Try DFlash2 speculative decoding for speed, once the baseline is stable (experimental
      upstream, qualified at 8K context only).
- [ ] Evaluate the standalone radiance engine (`llm_engine: radiance_engine`); needs a `.rad`
      conversion first.
- [ ] Evaluate a lighter local CLI client for the self-hosted model alongside Claude Code
      (for example late-cli); not assessed yet.
- [ ] Monthly: kernel and firmware update by hand, [docs/kernel-update.md](docs/kernel-update.md).
- [ ] When upstream promotes its vLLM 0.33 build to production, re-pin the image
      (procedure at the top of `images.yml`).
