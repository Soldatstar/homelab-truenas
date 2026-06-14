# =============================================================================
# Variables
# =============================================================================

# --- Proxmox Connection ---
variable "proxmox_endpoint" {
  description = "Proxmox API endpoint (e.g. https://192.168.1.100:8006)"
  type        = string
}

variable "proxmox_api_token" {
  description = "Proxmox API token in the format 'user@realm!tokenid=secret'"
  type        = string
  sensitive   = true
}

variable "proxmox_tls_insecure" {
  description = "Skip TLS verification (self-signed certs)"
  type        = bool
  default     = true
}

variable "proxmox_nodes" {
  description = "List of Proxmox node names (must match your cluster hostnames)"
  type        = list(string)
  default     = ["pve1", "pve2", "pve3"]
}

# --- Storage ---
variable "iso_datastore" {
  description = "Proxmox datastore for ISO/cloud images"
  type        = string
  default     = "local"
}

variable "vm_datastore" {
  description = "Proxmox datastore for VM disks"
  type        = string
  default     = "local-lvm"
}

variable "snippets_datastore" {
  description = "Proxmox datastore for cloud-init snippets (must have 'snippets' content type enabled)"
  type        = string
  default     = "local"
}

# --- Cloud Image ---
variable "debian13_checksum_sha512" {
  description = "SHA-512 checksum for the debian 13 cloud image (set to empty string to skip)"
  type        = string
  default     = ""
}

# --- VM Configuration ---
variable "vm_id_start" {
  description = "Starting VM ID for the K3s cluster"
  type        = number
  default     = 500
}

variable "vm_username" {
  description = "Default user for cloud-init"
  type        = string
  default     = "k3sadmin"
}

variable "vm_password" {
  description = "Default password for cloud-init user (use SSH keys instead if possible)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ssh_public_keys" {
  description = "List of SSH public keys for cloud-init"
  type        = list(string)
}

# --- Networking ---
variable "network_bridge" {
  description = "Proxmox network bridge"
  type        = string
  default     = "vmbr0"
}

variable "network_vlan_id" {
  description = "VLAN ID (set to null for no VLAN)"
  type        = number
  default     = null
}

variable "network_prefix" {
  description = "First 3 octets of your network (e.g. 192.168.1)"
  type        = string
  default     = "192.168.1"
}

variable "network_cidr" {
  description = "Network CIDR suffix (e.g. 24)"
  type        = string
  default     = "24"
}

variable "network_gateway" {
  description = "Default gateway IP"
  type        = string
  default     = "192.168.1.1"
}

variable "dns_servers" {
  description = "DNS server list"
  type        = list(string)
  default     = ["192.168.10", "192.168.15"]
}

variable "dns_domain" {
  description = "DNS search domain"
  type        = string
  default     = "k3s.local"
}
