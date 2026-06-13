# Creates a reusable VM template with a base Debian 12 cloud-init image.
# This template is used to quickly clone new VMs for the K3s cluster.
resource "proxmox_virtual_environment_vm" "k3s_template" {
  name      = "debian-12-k3s-template"
  node_name = var.proxmox_nodes[0] # Create template on the first node
  vm_id     = var.vm_id_start - 1  # Assign a unique ID before the node IDs

  description = "Debian 12 Cloud-Init Template for K3s – managed by Terraform"
  tags        = ["template", "terraform"]

  template = true

  # Hardware configuration for the template.
  machine = "q35"

  cpu {
    cores = 2
    type  = "host"
  }

  memory {
    dedicated = 2048
  }

  # Boot disk using the downloaded cloud image.
  # It will be resized when a VM is cloned from this template.
  disk {
    datastore_id = var.vm_datastore
    file_id      = proxmox_download_file.debian12_cloud_image[var.proxmox_nodes[0]].id
    interface    = "scsi0"
    size         = 10 # Small base size, will be resized on clone
    discard      = "on"
    ssd          = true
    iothread     = true
    file_format  = "raw"
  }

  scsi_hardware = "virtio-scsi-single"

  network_device {
    bridge = var.network_bridge
    model  = "virtio"
  }

  # Cloud-Init drive for the template.
  # Configuration will be applied on clone.
  initialization {
    datastore_id = var.vm_datastore
    type         = "nocloud"
  }

  agent {
    enabled = true
  }

  serial_device {}

  lifecycle {
    ignore_changes = [
      network_device,
      disk,
      initialization[0].user_account,
    ]
  }
}
