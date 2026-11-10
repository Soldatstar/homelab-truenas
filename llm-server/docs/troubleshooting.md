# Troubleshooting

Start with `docker logs --tail 200 vllm-radiance` and `llm-gpu-stats`.

## The engine never becomes healthy

| Symptom in the log | Likely cause | Action |
|---|---|---|
| Still compiling after many minutes on the first start | Cold Triton / inductor / AITER caches and graph capture | Wait. Ansible allows 45 minutes (`vllm_health_timeout_minutes`). Later starts reuse `/srv/llm/vllm-cache` |
| `[radiance] ERROR ...` then exit code 64 | The entrypoint rejected an inconsistent set of experimental flags | Reset `vllm_experimental` to all-off |
| HIP / "out of memory" during load or graph capture | Profile too large for the pool | `llm_profile: chat`; if still failing, lower `vllm_gpu_memory_utilization` to 0.85 |
| Errors mentioning MXFP4, Quark, W4A8 or a missing kernel table | The image cannot run the Quark checkpoint | Use the FP8 checkpoint (below) |
| `No HIP GPUs are available`, `/dev/kfd` errors | Driver did not bind, or devices not passed in | `ls -l /dev/kfd /dev/dri`; see bios-kernel-checklist.md |
| Hangs at start with both GPUs idle, or TP worker timeouts | P2P / all-reduce problem between the cards | Check the P2P report at the top of the log; verify IOMMU/ACS settings. There is an open RCCL report for two R9700s |
| `gfx1201` kernel or `libr4d` load errors after a kernel update | Driver or firmware regression | Roll back with kernel-update.md step 6 |

### Stale compile caches

After an image change the caches are namespaced by upstream, so they should not collide. If
a start fails in Triton or inductor right after an image update, clear them once:

```bash
docker compose -f /opt/llm/vllm-radiance/docker-compose.yml down
sudo rm -rf /srv/llm/vllm-cache/*
```

then re-run `site.yml --tags engine` (the next start recompiles).

## Output is garbled or tool calls are malformed

- Garbage text right after switching model or image points at the weight path. Upstream
  notes that the generic AITER W4A4 fallback is numerically wrong for one Qwen projection,
  which is why `RADIANCE_MXFP4_W4A8_MIN_M` must stay `0`. Confirm nothing in
  `vllm_experimental` is on, then try the FP8 checkpoint.
- Tool calls arriving as plain text: the parsers are `qwen3_coder` (tools) and `qwen3`
  (reasoning). A different model family needs different parsers in the compose template.
- MTP speculative decoding failed upstream's tool gate. Do not use it with Claude Code.

## FP8 fallback checkpoint

Native FP8 weights avoid the MXFP4 kernels entirely. They are larger (28.75 GiB), so the
context budget shrinks: upstream measured 128K x 2 or 256K x 1 at 85% allocation. The FP8
checkpoint (`Qwen/Qwen3.8-27B-FP8`) is already configured as the `fp8` entry of `llm_models`
and downloaded alongside the default, so switching is one command:

```bash
ansible-playbook playbooks/site.yml --ask-become-pass --ask-vault-pass --tags models,engine -e llm_model=fp8
ansible-playbook playbooks/smoke-test.yml --ask-become-pass --ask-vault-pass
```

It uses the `chat-fp8` profile (131,072 x 2, 85% GPU memory) automatically. The first start
compiles kernels again for the new weight format.

## Slow or stalling requests

- `vllm:num_preemptions_total` rising on `/metrics`: the KV pool is full, usually several
  very long conversations at once. Use `llm_profile: chat`, or accept it.
- First message of a long chat is slow, later ones fast: that is cold prefill followed by
  prefix-cache hits, and is expected.
- Every message is slow: check the smoke test's prefix-cache line. If warm is no faster
  than cold, prefix caching is not active.
- Open WebUI feels sluggish after each answer: background title/tag/follow-up generation at
  `xhigh` reasoning. Lower `vllm_default_reasoning_effort` or turn some of them off.
- Idle CPU usage is high: upstream documents a ROCm idle-CPU issue in
  `docs/ROCM_IDLE_CPU.md` of the vllm-radiance repository.

## GPU hardware

- **Fan not spinning under load** has been reported for the R9700 on kernel 7.0. Watch
  `watch -n 2 llm-gpu-stats` during the first long generation. If temperature climbs with
  0 RPM, stop the engine and check dmesg for `SMU` messages; a firmware update or rollback
  is the fix path.
- VRAM not released after a crash: `docker compose ... down`, then check `llm-gpu-stats`.
  If VRAM stays allocated, reboot.

## Firewall and connectivity

- Proxy gets connection timeouts: `sudo iptables -S LLM-INGRESS` must list 192.168.1.0/24
  (or your `llm_allowed_sources`), and
  `sudo iptables -S DOCKER-USER` must jump to `LLM-INGRESS` for `eno1np0`. Re-apply with
  `sudo systemctl restart llm-docker-user-firewall`.
- Containers cannot reach the internet (image pulls work, SearXNG does not): replies are
  admitted as ESTABLISHED; check that ufw's forward policy has not been changed.
- You cannot reach port 8000 or 3000 from a machine outside `llm_allowed_sources` (for
  example another VLAN): intended. Add its subnet to `llm_extra_allowed_sources` and run
  `site.yml --tags firewall`.
- HTTP 401 from the API: missing or wrong key. Claude Code must use `ANTHROPIC_AUTH_TOKEN`
  (Bearer), not `ANTHROPIC_API_KEY`.

## Claude Code

- Errors on `/v1/messages` while `/v1/chat/completions` works: enable LiteLLM
  (`litellm_enabled: true`) and point the proxy host at port 4000.
- "Prompt is too long": the conversation exceeded `max-model-len`. Use `/compact`, or a
  profile with 262,144.
- Requests to api.anthropic.com in your network logs: the env script was not sourced in
  that shell.

## Fallback engines

**llama.cpp** (automated, untested here). Serves OpenAI and Anthropic APIs on the same port,
so Open WebUI and Claude Code keep working. You choose the GGUF:

```bash
ansible-playbook playbooks/fallback-llamacpp.yml --ask-become-pass --ask-vault-pass \
  -e llamacpp_gguf_repo=<owner>/<repo>-GGUF -e llamacpp_gguf_file=<file>.gguf
```

It uses the Vulkan image by default (`-e llamacpp_backend=rocm` for the ROCm image), two
parallel slots and a 131,072-token total context split between them. Expect lower
throughput than vllm-radiance. Run `site.yml` to switch back.

**Official `rocm/vllm` image** (manual). AMD's stock vLLM image runs on gfx1201 without the
radiance kernels. It is not automated here because it cannot run the Quark MXFP4 path the
same way and is much slower on this card, but it is the reference for telling a radiance
bug from a driver bug: if the stock image also fails, the problem is the host.

**Standalone radiance engine**: see the README section; `llm_engine: radiance_engine`.
