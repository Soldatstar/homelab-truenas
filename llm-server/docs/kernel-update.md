# Manual kernel, firmware and Docker update

The kernel meta packages, `linux-firmware`, `linux-firmware-amd-graphics` are on `hold`, and
unattended-upgrades additionally skips kernel, firmware and Docker packages. Reason: a new
kernel or GPU firmware can break gfx1201 compute, and a Docker upgrade restarts the engine.
Security updates for everything else still install automatically.

Do this in a quiet moment, about once a month or when a kernel security notice matters to you.

1. **Record the working state.**

   ```bash
   uname -r
   dpkg -l linux-image-generic linux-firmware-amd-graphics docker-ce | tail -3
   ```

2. **Unhold and upgrade.**

   ```bash
   sudo apt-mark unhold linux-generic linux-image-generic linux-headers-generic \
        linux-firmware linux-firmware-amd-graphics
   sudo apt update
   sudo apt full-upgrade          # includes docker-ce and containerd.io
   ```

3. **Reboot.** `sudo reboot`. The previous kernel stays installed and selectable in GRUB.

4. **Check the driver.**

   ```bash
   uname -r
   ls -l /dev/kfd /dev/dri/renderD*
   sudo dmesg | grep -i amdgpu | grep -iE 'error|fail' || echo clean
   ```

5. **Re-apply holds and test** (from the Ansible controller; `site.yml` puts the holds back).

   ```bash
   ansible-playbook playbooks/site.yml --ask-become-pass --ask-vault-pass
   ansible-playbook playbooks/smoke-test.yml --ask-become-pass --ask-vault-pass
   ```

6. **If the smoke test fails:** reboot into the previous kernel (GRUB, "Advanced options"),
   confirm the smoke test passes there, and then pin it:

   ```bash
   sudo apt-mark hold linux-image-$(uname -r) linux-modules-$(uname -r)
   ```

   For a firmware regression, downgrade `linux-firmware-amd-graphics` to the version from
   step 1 (`sudo apt install linux-firmware-amd-graphics=<version>`), run
   `sudo update-initramfs -u`, reboot, and run `site.yml` to restore the holds.

Record the new known-good kernel and firmware versions in `VERSIONS.md`.
