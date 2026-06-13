# Defines local variables for the cluster configuration.
locals {
  k3s_nodes = {
    "k3s-server-01" = {
      node_name = var.proxmox_nodes[0]
      vm_id     = var.vm_id_start
      role      = "server"
      cores     = 5
      memory    = 10240 # 10 GB
      disk_size = 80    # GB
      ip        = "${var.network_prefix}.28"
    }
    "k3s-agent-01" = {
      node_name = var.proxmox_nodes[1]
      vm_id     = var.vm_id_start + 1
      role      = "agent"
      cores     = 5
      memory    = 12288 # 12 GB
      disk_size = 100   # GB
      ip        = "${var.network_prefix}.29"
    }
    "k3s-agent-02" = {
      node_name = var.proxmox_nodes[2]
      vm_id     = var.vm_id_start + 2
      role      = "agent"
      cores     = 5
      memory    = 12288 # 12 GB
      disk_size = 100   # GB
      ip        = "${var.network_prefix}.30"
    }
  }
}
