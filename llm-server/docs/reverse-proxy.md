# Reverse proxy (NPM Plus, 192.168.1.10)

The LLM host does no TLS and is not reachable directly. This page is what the proxy needs;
nothing here is deployed by Ansible.

## What the LLM host exposes

| Port | Bound to | Service | Allowed sources |
|---|---|---|---|
| 22/tcp | all | SSH | 192.168.1.0/24 (ufw) |
| 3000/tcp | 192.168.1.41 | Open WebUI (HTTP) | `llm_allowed_sources` (192.168.1.0/24) |
| 8000/tcp | 192.168.1.41 | Inference API (HTTP, API key) | `llm_allowed_sources` (192.168.1.0/24) |
| 4000/tcp | 192.168.1.41 | LiteLLM, only if `litellm_enabled` | `llm_allowed_sources` (192.168.1.0/24) |
| 9100/tcp | 192.168.1.41 | node-exporter, only if `llm_metrics_enabled` | `llm_metrics_sources` |

Ports 3000, 8000, 4000 and 9100 are Docker-published, so ufw does not see them. They are
restricted in the `DOCKER-USER` chain (`LLM-INGRESS`), re-applied on boot and on every
Docker restart by `llm-docker-user-firewall.service`. The allow-list is
`llm_allowed_sources` (default: the whole LAN, `192.168.1.0/24`) plus
`llm_extra_allowed_sources`, and it applies to every published port, so clients on the LAN
can also reach the services directly, without the proxy. To admit only the proxy, set
`llm_allowed_sources: ["192.168.1.10"]` and run `site.yml --tags firewall`.

## Proxy host 1: chat.viktornote.ch

- Forward to `http://192.168.1.41:3000`.
- **Websockets support: on** (Open WebUI streams over websockets).
- Force SSL, HTTP/2.
- Custom configuration:

  ```nginx
  proxy_buffering off;
  proxy_read_timeout 3600s;
  proxy_send_timeout 3600s;
  client_max_body_size 200m;
  ```

- Open WebUI is configured with `WEBUI_URL=https://chat.viktornote.ch`, secure cookies, and
  trusts forwarded headers from 192.168.1.10 only.
- Authentik in front: either a forward-auth in NPM Plus (Open WebUI keeps its own login),
  or trusted-header SSO: set `openwebui_trusted_email_header: X-authentik-email` (and
  optionally the name header) in `main.yml`. Trusted headers are only safe if nothing but
  the proxy can reach port 3000: with the default LAN-wide allow-list any LAN client could
  forge them, so first narrow `llm_allowed_sources` to the proxy, and make sure the proxy
  strips those headers from client requests.

## Proxy host 2: llm.viktornote.ch (LAN only by default)

- Forward to `http://192.168.1.41:8000`.
- **Access list: allow 192.168.1.0/24, deny all.** This is the default stance; the API key
  is a second factor, not the only one.
- Forward only the API paths. `/metrics`, `/health` and the docs pages are not protected by
  the API key:

  ```nginx
  location ~ ^/(metrics|docs|redoc|openapi.json) { return 404; }
  proxy_buffering off;              # token streaming (SSE)
  proxy_read_timeout 3600s;         # long prefills and long generations
  proxy_send_timeout 3600s;
  client_max_body_size 50m;         # 262K-token prompts are several MB of JSON
  ```

- Do not add proxy-level basic auth on this host: Claude Code and OpenAI clients send the
  key in `Authorization: Bearer`, and a second `Authorization` scheme would collide.

Routes behind it: `/v1/chat/completions`, `/v1/completions`, `/v1/models` (OpenAI) and
`/v1/messages` (Anthropic, used by Claude Code).

### Opening it externally

Only if you need Claude Code from outside the LAN, and preferably through a VPN instead.
If you do open it:

1. Remove the LAN-only access list on the proxy host (or add the specific external IPs).
2. Rotate `vault_llm_api_key` to a fresh 32-byte value and re-run `site.yml`.
3. Keep the `location` block above, and add rate limiting on the proxy.
4. Do not put Authentik forward-auth in front of this host: API clients cannot follow the
   login redirect.

Anyone with the key can use the GPUs and read nothing else; chats live in Open WebUI, not in
the engine.
