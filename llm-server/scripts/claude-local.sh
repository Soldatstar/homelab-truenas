#!/usr/bin/env bash
# Run Claude Code against the self-hosted model. Nothing to source: just run it.
#
#   ./claude-local.sh                 start Claude Code in the current directory
#   ./claude-local.sh -p "question"   any arguments are passed on to `claude`
#
# Settings (override from the environment if needed):
#   LLM_BASE_URL   default https://llm.viktornote.ch   (no /v1 suffix)
#   LLM_MODEL      default qwen3.8-27b
#   LLM_API_KEY    the engine key (vault_llm_api_key); asked for if unset.
#                  Put it in ~/.config/claude-local/key (chmod 600) to skip the prompt.
#
# The variables are set for this run only; your shell and other Claude Code
# sessions keep talking to the normal Anthropic service.
set -euo pipefail

LLM_BASE_URL="${LLM_BASE_URL:-https://llm.viktornote.ch}"
LLM_MODEL="${LLM_MODEL:-qwen3.8-27b}"
KEY_FILE="${HOME}/.config/claude-local/key"

command -v claude >/dev/null || { echo "claude is not installed or not on PATH" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required for the connection check" >&2; exit 1; }

if [ -z "${LLM_API_KEY:-}" ] && [ -r "$KEY_FILE" ]; then
    LLM_API_KEY="$(tr -d '[:space:]' < "$KEY_FILE")"
fi
if [ -z "${LLM_API_KEY:-}" ]; then
    read -rsp "LLM API key (vault_llm_api_key): " LLM_API_KEY
    echo
fi
# Strip whitespace and quotes that sneak in when copying from the vault output.
LLM_API_KEY="$(printf '%s' "$LLM_API_KEY" | tr -d '[:space:]"'"'")"
[ -n "$LLM_API_KEY" ] || { echo "empty API key" >&2; exit 1; }

# Check the server and the key before starting, so errors are clear.
status="$(curl -s -o /dev/null -m 15 -w '%{http_code}' \
    -H "Authorization: Bearer ${LLM_API_KEY}" "${LLM_BASE_URL}/v1/models" || true)"
case "$status" in
    200) ;;
    401) echo "Server reached, but it rejected the key (401). Use vault_llm_api_key, not the Open WebUI secret." >&2; exit 1 ;;
    502|503|504) echo "Proxy answered ${status}: the engine is down or still loading. Try again in a few minutes." >&2; exit 1 ;;
    000) echo "Could not reach ${LLM_BASE_URL} (DNS or network). Are you on the home LAN?" >&2; exit 1 ;;
    *) echo "Unexpected HTTP ${status} from ${LLM_BASE_URL}/v1/models" >&2; exit 1 ;;
esac

export ANTHROPIC_BASE_URL="$LLM_BASE_URL"
export ANTHROPIC_AUTH_TOKEN="$LLM_API_KEY" # sent as "Authorization: Bearer"
unset ANTHROPIC_API_KEY                     # would be sent as x-api-key, which the engine rejects

# Every model slot uses the one local model.
export ANTHROPIC_MODEL="$LLM_MODEL"
export ANTHROPIC_SMALL_FAST_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$LLM_MODEL"
export CLAUDE_CODE_SUBAGENT_MODEL="$LLM_MODEL"

# The model's template accepts reasoning effort low, medium or xhigh, not "high".
export CLAUDE_CODE_EFFORT_LEVEL="${CLAUDE_CODE_EFFORT_LEVEL:-medium}"

export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export API_TIMEOUT_MS=1800000 # a cold long prefill can take minutes

echo "Claude Code -> ${LLM_BASE_URL} (${LLM_MODEL})"
exec claude "$@"
