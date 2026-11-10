# Next steps

State on 2026-11-10: everything in `llm-server/` is written, passes `ansible-lint`
(production profile), `yamllint` and `--syntax-check`, and all templates render to valid
YAML/JSON. **Nothing has been run against the host yet, and nothing is committed.**

Work through these in order. Details for each are in [README.md](README.md).

## 1. Before the first run

- [ ] Review the files and commit them (`git add llm-server .gitignore`).
- [ ] Make the host's SSH key usable from WSL, where Ansible runs:
      `ssh-copy-id viktor@192.168.1.41` from WSL, or copy the Windows key into `~/.ssh`.
      Check with `ansible -i inventory/inventory.yml llm -m ping` in `llm-server/ansible`.
- [ ] Create the vault:
      ```bash
      cd llm-server/ansible
      cp inventory/group_vars/llm/vault.yml.example inventory/group_vars/llm/vault.yml
      # fill in: openssl rand -hex 32 for each secret, real admin email and password
      ansible-vault encrypt inventory/group_vars/llm/vault.yml
      ```
- [ ] Skim `inventory/group_vars/llm/main.yml`. The values most worth a second look:
      `llm_profile`, `vllm_default_reasoning_effort`, the Open WebUI toggles.
- [ ] BIOS: confirm Above 4G Decoding and Resizable BAR are on
      ([docs/bios-kernel-checklist.md](docs/bios-kernel-checklist.md)). The host already
      shows both cards, one NUMA node and IOMMU off, so this is probably fine as is.

## 2. Deploy

- [ ] Dry run: `ansible-playbook playbooks/site.yml --ask-become-pass --ask-vault-pass --check --diff`
      (Docker-dependent tasks fail or skip on a host without Docker; that is expected once).
- [ ] Real run: `ansible-playbook playbooks/site.yml --ask-become-pass --ask-vault-pass`
      Expect roughly 20 GB of model download, a 4 GB image pull, then up to 45 minutes of
      kernel compilation and graph capture on the first start.
- [ ] While it loads, watch `docker logs -f vllm-radiance` and `watch -n 2 llm-gpu-stats` on
      the host. Check that both fans spin once the GPUs are busy.

## 3. Verify

- [ ] `ansible-playbook playbooks/smoke-test.yml --ask-become-pass --ask-vault-pass`
- [ ] Read the report. These are the open questions it answers:

  | Check | If it fails |
  |---|---|
  | Engine healthy with the `chat` profile (131,072 x 4) | Lower `vllm_gpu_memory_utilization` to 0.85, or fall back to the FP8 checkpoint |
  | Chat answer correct, tool call well-formed | FP8 checkpoint or previous digest, see troubleshooting |
  | `/v1/messages` tool round trip | `litellm_enabled: true`, proxy to port 4000 |
  | Prefix cache: warm TTFT much lower than cold | Check the two prefix flags in the container command |
  | Open WebUI admin sign-in, signup closed | Open WebUI env names may have changed in v0.13; check its logs |
  | API returns 401 without the key and 200 with it | Key mismatch between the vault and the running container: re-run `site.yml --tags engine` |

- [ ] Reboot the host once and re-run the smoke test, to prove the firewall unit and the
      containers come back on their own. Also check `sudo iptables -S LLM-INGRESS` lists
      192.168.1.0/24, and that a host outside it (phone on mobile data, another VLAN) cannot
      reach :8000.
- [ ] Update the "Not verified" list in [VERSIONS.md](VERSIONS.md) with what passed.

## 4. Reverse proxy (NPM Plus, by hand)

- [ ] `chat.viktornote.ch` -> `http://192.168.1.41:3000`, websockets on.
- [ ] `llm.viktornote.ch` -> `http://192.168.1.41:8000`, access list LAN only, block
      `/metrics` and `/docs`.
- [ ] Snippets and the Authentik notes: [docs/reverse-proxy.md](docs/reverse-proxy.md).

## 5. Use it

- [ ] Open `https://chat.viktornote.ch`, sign in as the vault admin, start two chats at once.
- [ ] Claude Code: `. .\llm-server\scripts\claude-code-env.ps1`, then `claude`.
- [ ] Baseline numbers: `python3 scripts/bench.py --base-url https://llm.viktornote.ch --model qwen3.8-27b`
      (upstream reference: about 53 tok/s single, 102 tok/s at two streams). Note them in
      `VERSIONS.md`.

## 6. Later, optional

- [ ] Passwordless sudo for Ansible: `playbooks/sudo-nopasswd.yml` (opt-in, read the header).
- [ ] Try the untested `long` (262,144 x 4) or `coding` (262,144 x 2) profile with
      `-e llm_profile=long`, and record in `VERSIONS.md` whether it starts.
- [ ] Narrow `llm_allowed_sources` to the proxy (`192.168.1.10`) if you want only the proxy
      to reach the services; required before enabling Authentik trusted-header SSO.
- [ ] Prometheus: `llm_metrics_enabled: true` and `llm_metrics_sources`.
- [ ] Decide on Authentik in front of Open WebUI (forward-auth or trusted header).
- [ ] Try DFlash2 speculative decoding for speed, once the baseline is stable. It is
      experimental upstream and was qualified at 8K context only.
- [ ] Evaluate the standalone radiance engine (`llm_engine: radiance_engine`); needs a
      `.rad` conversion first.
- [ ] Monthly: kernel and firmware update by hand, [docs/kernel-update.md](docs/kernel-update.md).
- [ ] When upstream promotes its vLLM 0.33 build to production, re-pin the image
      (procedure at the top of `images.yml`).
