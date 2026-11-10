# Point Claude Code at the local model for this PowerShell session.
#
#   . .\claude-code-env.ps1        (dot-source it, then run: claude)
#
# The API key is never stored here. Set $env:LLM_API_KEY beforehand or type it
# when prompted (it is vault_llm_api_key from the Ansible vault).
# If the LiteLLM proxy is used instead of the native endpoint, point
# $LlmBaseUrl at that proxy host and use vault_litellm_master_key.

$LlmBaseUrl = "https://llm.viktornote.ch"   # no /v1: Claude Code appends /v1/messages
$LlmModel = "qwen3.8-27b"                   # llm_served_model_name ("claude-local" is an alias)

if (-not $env:LLM_API_KEY) {
    $secure = Read-Host -Prompt "LLM API key" -AsSecureString
    $env:LLM_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
}

$env:ANTHROPIC_BASE_URL = $LlmBaseUrl
$env:ANTHROPIC_AUTH_TOKEN = $env:LLM_API_KEY    # sent as "Authorization: Bearer"
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue

# Every model slot maps to the one local model: main, small/fast (background
# tasks), each tier alias, and subagents.
$env:ANTHROPIC_MODEL = $LlmModel
$env:ANTHROPIC_SMALL_FAST_MODEL = $LlmModel
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = $LlmModel
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = $LlmModel
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = $LlmModel
$env:CLAUDE_CODE_SUBAGENT_MODEL = $LlmModel

# No telemetry, update checks or error reports to Anthropic from this session.
$env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1"

# Local prefill of a long context can take minutes on a cold cache.
$env:API_TIMEOUT_MS = "1800000"

Write-Host "Claude Code -> $LlmBaseUrl ($LlmModel). Run: claude"
