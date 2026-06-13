# Creates the K3s server and agent VMs by cloning the template.
resource "proxmox_virtual_environment_vm" "k3s" {
  for_each = local.k3s_nodes

  name      = each.key
  node_name = each.value.node_name
  vm_id     = each.value.vm_id

  description = "K3s ${each.value.role} node – managed by Terraform"
  tags        = ["k3s", each.value.role, "terraform"]

  # Clone from the Debian 12 template.
  clone {
    vm_id     = proxmox_virtual_environment_vm.k3s_template.vm_id
    full      = true
    node_name = proxmox_virtual_environment_vm.k3s_template.node_name
  }

  on_boot = true
  started = true

  # Hardware settings are overridden from the template.
  machine = "q35"

  cpu {
    cores = each.value.cores
    type  = "host"
  }

  memory {
    dedicated = each.value.memory
  }

  # Resize the boot disk to the size specified in the locals.
  disk {
    datastore_id = var.vm_datastore
    interface    = "scsi0"
    size         = each.value.disk_size
    discard      = "on"
    ssd          = true
    iothread     = true
  }

  scsi_hardware = "virtio-scsi-single"

  network_device {
    bridge  = var.network_bridge
    model   = "virtio"
    vlan_id = var.network_vlan_id
  }

  # Cloud-Init configuration for network, users, and custom setup.
  initialization {
    datastore_id = var.vm_datastore

    ip_config {
      ipv4 {
        address = "${each.value.ip}/${var.network_cidr}"
        gateway = var.network_gateway
      }
    }

    dns {
      servers = var.dns_servers
      domain  = var.dns_domain
    }

    user_account {
      keys     = var.ssh_public_keys
      username = var.vm_username
      password = var.vm_password
    }

    # Use vendor_data for additional setup like package installation and configuration.
    # This is preferred over user_data to avoid conflicts with Proxmox-generated settings.
    vendor_data_file_id = proxmox_virtual_environment_file.cloud_init_vendor_data[each.value.node_name].id
  }

  agent {
    enabled = true
    timeout = "20m" # Increased timeout to allow for cloud-init package installs and reboots.
  }

  serial_device {}

  lifecycle {
    ignore_changes = [
      initialization[0].user_account[0].password,
      clone, # Ignore changes to the clone block after creation.
    ]
  }
}
