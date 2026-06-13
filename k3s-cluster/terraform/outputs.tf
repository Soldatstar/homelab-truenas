# Defines the outputs for the K3s cluster.
output "k3s_node_ips" {
  description = "IP addresses of the K3s nodes."
  value = {
    for name, node in local.k3s_nodes : name => node.ip
  }
}

output "ssh_command" {
  description = "Command to SSH into the K3s server node."
  value       = "ssh ${var.vm_username}@${local.k3s_nodes["k3s-server-01"].ip}"
}

output "k3s_install_server" {
  description = "Command to install the K3s server on the first master node."
  value       = "curl -sfL https://get.k3s.io | sh -s - server --cluster-init --tls-san=${local.k3s_nodes["k3s-server-01"].ip}"
}

output "k3s_install_agent" {
  description = "Command to install K3s agents on worker nodes."
  value       = "curl -sfL https://get.k3s.io | K3S_URL=https://${local.k3s_nodes["k3s-server-01"].ip}:6443 K3S_TOKEN=<TOKEN> sh -"
}
