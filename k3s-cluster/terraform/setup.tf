# Download the Debian 12 cloud image to each Proxmox node's local storage.
# This ensures the image is available on the node where the VM will be created.
resource "proxmox_download_file" "debian12_cloud_image" {
  for_each = toset(var.proxmox_nodes)

  content_type = "iso"
  datastore_id = var.iso_datastore
  node_name    = each.value

  url       = "https://cloud.debian.org/images/cloud/trixie/latest/debian-13-generic-amd64.qcow2"
  file_name = "debian-13-generic-amd64.img"

  checksum_algorithm = "sha512"
  checksum           = var.debian12_checksum_sha512
}
