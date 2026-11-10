# Versions and sources

Recorded 2026-11-10. Every decision in this folder traces back to one of these.

## Pinned components

| Component | Version / tag | Pin |
|---|---|---|
| vllm-radiance | Docker Hub `1.0.387` = `sha-1855cd8cdb3b`, pushed 2026-09-23. `VERSION` at that commit: `1.1.0-rc1.vllm0.30.0` | `sha256:c0e8f375de5a...` |
| Model | `amd/Qwen3.8-27B-Quark-AWQ-MXFP4`, last modified 2026-11-03, public, Apache-2.0 | commit `93245f7c00f1...` |
| Model (alternative) | `Qwen/Qwen3.8-27B-FP8`, public, 27.8B parameters, modified 2026-11-07 | commit `c3a462cc3d38...` |
| CPU model | `ggml-org/Qwen3.6-35B-A3B-GGUF`, `Qwen3.6-35B-A3B-Q4_K_M.gguf` (19.1 GiB), modified 2026-11-08 | commit `eb0b3cc97fec...` |
| llama.cpp CPU server | `ghcr.io/ggml-org/llama.cpp:server` on 2026-11-10 | `sha256:4d2de15a0ffb...` |
| Open WebUI | v0.13.3 | `sha256:46b59158e655...` |
| SearXNG | `latest` on 2026-11-10 | `sha256:287af61f1a13...` |
| Postgres (optional) | 17 | `sha256:ff87138949ad...` |
| LiteLLM (optional) | `main-stable` on 2026-11-10 (release v1.108.4) | `sha256:c560d3171368...` |
| node-exporter (optional) | v1.12.1 | `sha256:1b4e4438faca...` |
| radiance engine (optional) | `latest` on 2026-11-10 (source tree 1.17.0) | `sha256:c2acbaa373c8...` |
| llama.cpp (fallback) | `server-vulkan` / `server-rocm` on 2026-11-10 | see `images.yml` |

Full digests are in `ansible/inventory/group_vars/llm/images.yml`.

## Host as observed

Ubuntu 26.04, kernel 7.0.0-43-generic, `linux-firmware-amd-graphics` 20260319, one NUMA
node, no IOMMU groups (IOMMU off), both R9700s bound by in-kernel amdgpu (`/dev/kfd`,
`renderD128`, `renderD129`), render GID 991, video GID 44. No Docker before the first run.

## Upstream sources

**magiccodingman/vllm-radiance** (GitHub mirror of the GitLab source)
- `README.md` on `main`: stack description. Its current tree is a vLLM 0.33 candidate
  marked "Upgrade candidate; not production-qualified". That is why this setup pins the
  0.30 build instead of `latest`.
- At commit `1855cd8cdb3b` (the pinned image), read in full or searched:
  `docker-compose.yml`, `.env.example`, `radiance_entrypoint.sh`, `Dockerfile`, `VERSION`,
  `README.md`, `DOCKERHUB.md`, `docs/COMPOSE_CAPACITY.md`.
  - Compose command, environment block, devices, capabilities, `ipc: host`, health check
    and the cache paths (`/cache/vllm`, `/cache/inductor`, `/cache/triton`, `/cache/aiter`,
    `/cache/tunableop`) are taken from that compose file.
  - Parsers: `--tool-call-parser=qwen3_coder`, `--reasoning-parser=qwen3`,
    `--enable-auto-tool-choice`.
  - MXFP4 support in this build: the Dockerfile applies `patch_quark_mxfp4` and ships
    `radiance_mxfp4.py`; the README's Quark block gives the environment used here.
  - Prefix caching for the GDN hybrid: compose comment and `COMPOSE_CAPACITY.md`
    ("576,001 usable KV tokens", 128K x 4 with zero preemptions, 12.8x TTFT at 32K).
- `docs/V030_PUBLICATION_20260922.md`: tool-gate results (non-speculative and DFlash 30/30,
  MTP 29/30) and throughput (53.3 tok/s at one stream, 101.8 at two).

**StillDeadcode** (Codeberg)
- `vllm-radiance` README: "This project is no longer being maintained", recommends the
  standalone engine.
- `radiance` README and `deploy/compose/{common.yaml,qwen3.8-27b-mxfp4.yaml,.env.example}`
  on `main` (2026-11-05): basis of the optional `radiance_engine` role.

**AMD ROCm**
- Compatibility matrix: Radeon AI PRO R9000 series supported on Ubuntu 26.04.1 with the GA
  7.0 kernel. No host ROCm packages are installed; ROCm userspace is inside the images.
- Open reports worth knowing: R9700 fan not spinning under load on 26.04 / kernel 7.0
  (ROCm/legacy-rocm-build#6101) and an RCCL all-reduce failure on two R9700s
  (ROCm/rocm-systems#13616).

**vLLM**
- Anthropic Messages router (`/v1/messages`) is documented for upstream vLLM from at least
  v0.15, so it should be present in the 0.30 base.

## Not verified

These are assumptions until `smoke-test.yml` has passed on the host:

1. Nothing here has been executed against the host yet.
2. `/v1/messages` works in this fork's build, including with `--api-key`.
3. The `chat` profile (131,072 x 4, prefix caching + align) is upstream's qualified
   configuration, but was measured on a DFlash2 build; the non-speculative start here is
   unverified. The `long` and `coding` profiles (262,144) are untested: upstream ran
   262,144 only with prefix caching off.
4. Open WebUI v0.13.3 accepts every environment variable used and still allows the first
   signup to become admin while public signup is off.
5. `--enable-prompt-tokens-details` and the `memlock`/`nofile` ulimits are additions that
   upstream's compose does not have.
6. The `radiance_engine` and `llamacpp_fallback` roles are untested skeletons.
7. The CPU model (`llm_cpu_model` role) has not been run: that the `server` image starts with
   these flags, has `curl` for its health check, loads the GGUF, and reaches the expected speed.
   The `fp8` entry of `llm_models` is also untested.

Checked: Docker's apt repository has a `resolute` (26.04) suite.
