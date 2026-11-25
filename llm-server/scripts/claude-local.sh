#!/usr/bin/env bash
# Run Claude Code against the self-hosted model. Nothing to source: just run it.
#
#   ./claude-local.sh                 start Claude Code in the current directory
#   ./claude-local.sh -p "question"   any arguments are passed on to `claude`
#
# It uses its own Claude Code profile (CLAUDE_PROFILE_DIR), so your normal Claude Code login,
# settings and history are not touched. From ../claude-code in this repository it gets the
# settings, the two subagents (worker, scout) and the orchestrator rules (added to the main
# session's system prompt only). Web search goes through an MCP server (mcp.json, needs
# Node 22+) to SearXNG on the LLM host; set SEARXNG_URL to point it elsewhere.
#
# Settings (override from the environment if needed):
#   LLM_BASE_URL   default https://llm.viktornote.ch   (no /v1 suffix)
#   LLM_MODEL      default flashnext-uncensored (radiance); qwen3.8-27b with vllm-radiance
#   CLAUDE_PROFILE_DIR  default ~/.config/claude-local/profile
#   LLM_API_KEY    the engine key (vault_llm_api_key); asked for if unset.
#                  Put it in ~/.config/claude-local/key (chmod 600) to skip the prompt.
#
# The variables are set for this run only; your shell and other Claude Code
# sessions keep talking to the normal Anthropic service.
set -euo pipefail

LLM_BASE_URL="${LLM_BASE_URL:-https://llm.viktornote.ch}"
LLM_MODEL="${LLM_MODEL:-flashnext-uncensored}"
KEY_FILE="${HOME}/.config/claude-local/key"
PROFILE_DIR="${CLAUDE_PROFILE_DIR:-${HOME}/.config/claude-local/profile}"
SOURCE_DIR="$(cd "$(dirname "$(readlink -f "$0")")/../claude-code" && pwd)"

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

# A separate profile. The repository stays the source of truth: the agents are linked and
# settings are passed with --settings, so Claude Code never rewrites the tracked file.
mkdir -p "$PROFILE_DIR/agents"
for f in "$SOURCE_DIR"/agents/*.md; do ln -sfn "$f" "$PROFILE_DIR/agents/$(basename "$f")"; done
export CLAUDE_CONFIG_DIR="$PROFILE_DIR"

# read_page (mcp.json) needs trafilatura. It gets its own virtualenv on this machine, built once
# and rebuilt when tools/requirements.txt changes.
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
REQ="$SOURCE_DIR/tools/requirements.txt"
VENV="${XDG_CACHE_HOME:-$HOME/.cache}/claude-local/venv-$(sha256sum "$REQ" | cut -c1-12)"
if [ ! -f "$VENV/.ready" ]; then
    echo "Installing the page reader ($(tr '\n' ' ' < "$REQ")) into $VENV"
    rm -rf "$VENV"
    python3 -m venv "$VENV" || { echo "could not create a virtualenv (Debian/Ubuntu: apt install python3-venv)" >&2; exit 1; }
    "$VENV/bin/pip" install --quiet --disable-pip-version-check -r "$REQ"
    touch "$VENV/.ready"
fi
export CLAUDE_LOCAL_PYTHON="$VENV/bin/python"
export CLAUDE_LOCAL_TOOLS="$SOURCE_DIR/tools"

# Every model slot uses the one local model, subagents included.
export ANTHROPIC_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$LLM_MODEL" # also used for background requests
export ANTHROPIC_DEFAULT_FABLE_MODEL="$LLM_MODEL"
export CLAUDE_CODE_SUBAGENT_MODEL="$LLM_MODEL"
export CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1

# The model's template accepts reasoning effort low, medium or xhigh, not "high".
export CLAUDE_CODE_EFFORT_LEVEL="${CLAUDE_CODE_EFFORT_LEVEL:-medium}"

echo "Claude Code -> ${LLM_BASE_URL} (${LLM_MODEL}), profile ${PROFILE_DIR}"
# --mcp-config takes several values, so an option must follow it before any user arguments.
exec claude --mcp-config "$SOURCE_DIR/mcp.json" --settings "$SOURCE_DIR/settings.json" \
    --append-system-prompt "$(cat "$SOURCE_DIR/orchestrator.md")" "$@"
