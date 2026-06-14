# This resource represents the local Debian 13 cloud image.
# It assumes the file already exists on each Proxmox node at the specified path.
# This is used to create a dependency for other resources that need the image.
resource "null_resource" "debian13_cloud_image" {
  for_each = toset(var.proxmox_nodes)

  triggers = {
    # This is a logical name for the image. The actual path is on the Proxmox node.
    file_path = "/var/lib/vz/template/iso/debian-13-generic-amd64.img"
  }

}
