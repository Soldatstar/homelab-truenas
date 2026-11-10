#!/bin/sh
# Point Claude Code at the local model for this shell session.
#
#   . ./claude-code-env.sh        (source it, then run: claude)
#
# The API key is never stored here. Export LLM_API_KEY beforehand or type it
# when prompted (it is vault_llm_api_key from the Ansible vault).
# If the LiteLLM proxy is used instead of the native endpoint, point
# LLM_BASE_URL at that proxy host and use vault_litellm_master_key.

LLM_BASE_URL="${LLM_BASE_URL:-https://llm.viktornote.ch}" # no /v1: Claude Code appends /v1/messages
LLM_MODEL="${LLM_MODEL:-qwen3.8-27b}"                     # llm_served_model_name ("claude-local" is an alias)

if [ -z "${LLM_API_KEY:-}" ]; then
    printf 'LLM API key: '
    stty -echo 2>/dev/null
    read -r LLM_API_KEY
    stty echo 2>/dev/null
    printf '\n'
fi

export ANTHROPIC_BASE_URL="$LLM_BASE_URL"
export ANTHROPIC_AUTH_TOKEN="$LLM_API_KEY" # sent as "Authorization: Bearer"
unset ANTHROPIC_API_KEY

# Every model slot maps to the one local model: main, small/fast (background
# tasks), each tier alias, and subagents.
export ANTHROPIC_MODEL="$LLM_MODEL"
export ANTHROPIC_SMALL_FAST_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$LLM_MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$LLM_MODEL"
export CLAUDE_CODE_SUBAGENT_MODEL="$LLM_MODEL"

# No telemetry, update checks or error reports to Anthropic from this session.
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Local prefill of a long context can take minutes on a cold cache.
export API_TIMEOUT_MS=1800000

echo "Claude Code -> $LLM_BASE_URL ($LLM_MODEL). Run: claude"
