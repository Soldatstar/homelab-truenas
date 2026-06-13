# Defines the cloud-init vendor data for K3s nodes.
# This script installs necessary packages, configures kernel modules,
# and sets sysctl parameters for Kubernetes.
resource "proxmox_virtual_environment_file" "cloud_init_vendor_data" {
  for_each = toset(var.proxmox_nodes)

  content_type = "snippets"
  datastore_id = var.snippets_datastore
  node_name    = each.value

  source_raw {
    data = <<-EOF
#cloud-config
package_update: true
package_upgrade: true

packages:
  - qemu-guest-agent
  - curl
  - gnupg
  - open-iscsi
  - nfs-common
  - jq
  - htop
  - net-tools
  - apt-transport-https
  - ca-certificates

runcmd:
  - "hostnamectl set-hostname ${each.key}"
  - systemctl enable --now qemu-guest-agent
  # Enable kernel modules for K3s / Longhorn
  - modprobe br_netfilter
  - modprobe overlay
  - modprobe iscsi_tcp
  - echo "br_netfilter" >> /etc/modules-load.d/k3s.conf
  - echo "overlay" >> /etc/modules-load.d/k3s.conf
  - echo "iscsi_tcp" >> /etc/modules-load.d/k3s.conf
  # Sysctl settings for Kubernetes
  - |
    cat <<SYSCTL > /etc/sysctl.d/99-k3s.conf
    net.bridge.bridge-nf-call-iptables  = 1
    net.bridge.bridge-nf-call-ip6tables = 1
    net.ipv4.ip_forward                 = 1
    SYSCTL
  - sysctl --system

# Grow the root partition to fill the disk
growpart:
  mode: auto
  devices: ["/"]

resize_rootfs: true
    EOF

    file_name = "k3s-cloud-init-vendor.yaml"
  }
}