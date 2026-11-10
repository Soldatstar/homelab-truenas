#!/bin/sh
# Managed by Ansible (llm_monitoring).
# Reads AMD GPU state from amdgpu sysfs. No ROCm userspace required.
#   llm-gpu-stats          human-readable table
#   llm-gpu-stats --prom   Prometheus text format (for the textfile collector)
set -eu

mode="${1:-}"
read_file() { cat "$1" 2>/dev/null || echo ""; }

[ "$mode" = "--prom" ] || printf '%-14s %6s %6s %8s %8s %12s\n' PCI "LOAD%" "TEMPC" "FANRPM" "POWERW" "VRAM(MiB)"

for dev in /sys/class/drm/card[0-9]*/device; do
    [ "$(read_file "$dev/vendor")" = "0x1002" ] || continue
    pci=$(basename "$(readlink -f "$dev")")
    busy=$(read_file "$dev/gpu_busy_percent")
    used=$(read_file "$dev/mem_info_vram_used")
    total=$(read_file "$dev/mem_info_vram_total")
    temp=""; fan=""; power=""
    for hw in "$dev"/hwmon/hwmon*; do
        [ -d "$hw" ] || continue
        temp=$(read_file "$hw/temp1_input")
        fan=$(read_file "$hw/fan1_input")
        power=$(read_file "$hw/power1_average")
        [ -n "$power" ] || power=$(read_file "$hw/power1_input")
    done
    if [ "$mode" = "--prom" ]; then
        l="pci=\"$pci\""
        [ -z "$busy" ] || echo "llm_gpu_busy_percent{$l} $busy"
        [ -z "$used" ] || echo "llm_gpu_vram_used_bytes{$l} $used"
        [ -z "$total" ] || echo "llm_gpu_vram_total_bytes{$l} $total"
        [ -z "$temp" ] || echo "llm_gpu_temperature_celsius{$l} $((temp / 1000))"
        [ -z "$fan" ] || echo "llm_gpu_fan_rpm{$l} $fan"
        [ -z "$power" ] || echo "llm_gpu_power_watts{$l} $((power / 1000000))"
    else
        printf '%-14s %6s %6s %8s %8s %12s\n' "$pci" "${busy:--}" \
            "$([ -n "$temp" ] && echo $((temp / 1000)) || echo -)" "${fan:--}" \
            "$([ -n "$power" ] && echo $((power / 1000000)) || echo -)" \
            "$([ -n "$used" ] && echo "$((used / 1048576))/$((total / 1048576))" || echo -)"
    fi
done
