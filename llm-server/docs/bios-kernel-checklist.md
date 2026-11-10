# BIOS and kernel checklist

BIOS is set by hand; Ansible only checks the result (`/dev/kfd` and two render nodes must
exist, or `host_prep` fails). Menu names vary by board vendor.

## BIOS (EPYC 7642, Rome)

| Setting | Value | Why |
|---|---|---|
| Above 4G Decoding | Enabled | Required to map 32 GB cards at all |
| Resizable BAR (Re-Size BAR) | Enabled | Full VRAM BAR; upstream reads kernel arguments over the link without it |
| CSM | Disabled | ReBAR needs pure UEFI boot |
| PCIe link speed for the GPU slots | Auto or Gen4 | Both cards on CPU-attached x16 slots |
| SR-IOV | Disabled | Not used |
| IOMMU (AMD-Vi) | Disabled, or Enabled with `iommu=pt` | See below |
| PCIe ACS | Disabled / Auto | ACS forces peer-to-peer traffic through the root complex |
| NUMA nodes per socket (NPS) | NPS1 | See below |
| SMT | Enabled | Default |
| Global C-states, power profile | Default; avoid aggressive power saving if latency is jittery | |

### IOMMU and peer-to-peer

Tensor parallel moves data between the two cards on every layer (upstream's `R4D` all-reduce
uses direct P2P, with RCCL as the fallback). The entrypoint prints a P2P and bandwidth
report at start; check it in `docker logs vllm-radiance`.

- **Current state of this host: IOMMU is off** (`/sys/kernel/iommu_groups` is empty). That
  is the simplest configuration for P2P and needs no kernel parameter. Keep it unless you
  need virtualisation on this machine.
- If you enable the IOMMU, set `host_prep_kernel_cmdline_extra: "iommu=pt"` in
  `group_vars/llm/main.yml` and re-run `site.yml` (writes a grub drop-in, reboot required).
  Passthrough mode avoids DMA remapping overhead for the GPUs.
- Do not enable ACS overrides or put the cards behind a PCIe switch with ACS enabled; that
  redirects P2P through the root complex and costs throughput.

### NUMA

The 7642 is a single socket, and the host currently reports **one NUMA node** (NPS1). Keep
it. With NPS2 or NPS4 the two cards can land in different nodes, and the engine's host
memory would then need pinning (`RADIANCE_NUMA_BIND=auto`, not wired up here because it is a
no-op on one node). DDR4-2666 across all eight channels matters more than NPS for prefill.

## Kernel and driver

- Ubuntu 26.04 GA kernel 7.0 with the in-tree `amdgpu` driver supports gfx1201. AMD lists
  this combination as supported for the R9700. **No host ROCm, no DKMS driver.** ROCm
  userspace lives inside the container image.
- GPU firmware comes from `linux-firmware-amd-graphics`. It and the kernel meta packages are
  held; update them with [kernel-update.md](kernel-update.md).

## Checks

```bash
ls -l /dev/kfd /dev/dri/renderD*                 # kfd + two render nodes
sudo dmesg | grep -i amdgpu | grep -iE 'vram|bar|error'
lspci -vv -s 81:00.0 | grep LnkSta               # upstream port of card 1: expect 16GT/s, x16
lspci -vv -s c1:00.0 | grep LnkSta               # upstream port of card 2
ls /sys/kernel/iommu_groups | wc -l              # 0 = IOMMU off
lscpu | grep 'NUMA node(s)'                      # 1
llm-gpu-stats                                    # temperature, fan, VRAM per card
```

Note on link speed: `lspci` on the VGA function itself (`83:00.0`, `c3:00.0`) shows the
card's internal link, not the slot. Read the link status on the upstream ports
`81:00.0` and `c1:00.0`.

Watch the fans on the first long run (`watch -n 2 llm-gpu-stats`): there is an open report of
an R9700 fan not spinning under load on this kernel generation.
