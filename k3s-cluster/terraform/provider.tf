# Configure the Proxmox provider.
# The endpoint and API token are sourced from variables.
provider "proxmox" {
  endpoint  = var.proxmox_endpoint
  api_token = var.proxmox_api_token
  insecure  = var.proxmox_tls_insecure

  # Configure SSH access for provisioning.
  # Assumes SSH agent is running.
  ssh {
    agent    = true
    username = "root"
  }
}
