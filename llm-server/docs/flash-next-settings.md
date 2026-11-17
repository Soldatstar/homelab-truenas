# Flash-Next: reasoning, sampling and Open WebUI presets

For `radiance_model=uncensored_v4` (served as `flashnext-uncensored`). Facts below come from the
Qwen3.8-Flash-Next card, the orcarouter abliteration card and radiance's 1.8.1 docs. The running
engine is **2.1.0**, so anything marked *check* must be confirmed on the host first (commands in
section 1). Section 1b records what the running 2.1.0 server reported.

## 1. Check what the engine really supports (read-only)

```bash
export LLM_API_KEY=...    # vault_llm_api_key
# which reasoning levels the engine takes, and its request defaults
curl -s -H "Authorization: Bearer $LLM_API_KEY" http://192.168.1.41:8000/server_info \
  | python3 -m json.tool | grep -i -E -B1 -A4 'reasoning|request_defaults|temperature|top_'
# the sampler defaults it printed at startup, with their source (default / file / flag)
sudo docker logs radiance 2>&1 | grep -i -A30 'CONFIGURATION' | head -60
# the keys this version accepts (YAML keys mirror the flags without "--")
sudo docker exec radiance radiance --help | grep -i -E 'reason|think|temp|top-|min-p|presence|generation|chat-template|served'
# does "high" work, and does "none" switch thinking off?
for e in none high; do curl -s http://192.168.1.41:8000/v1/chat/completions \
  -H "Authorization: Bearer $LLM_API_KEY" -H 'Content-Type: application/json' \
  -d "{\"model\":\"flashnext-uncensored\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 17*23?\"}],\"reasoning_effort\":\"$e\",\"max_tokens\":300}" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print("'$e'", "->", json.dumps(d)[:300])'; done
```

## 1b. Verified on your server (radiance 2.1.0, uncensored v4, `long` profile)

- **Sampling defaults come from the file:** `/server_info` reports temperature 1.0, top_k 20,
  top_p 0.95, min_p 0, presence 0, which is Qwen's thinking set. Thinking chats need no sampling
  override; only the Fast preset does.
- **Reasoning:** the engine's own default is unset (the template's `xhigh` applies). Accepted values:
  `none`, `minimal` (both turn thinking off), `low`, `medium`, `xhigh`. `"high"` is **rejected with
  a 400** ("not a level this model's chat template takes"), so Open WebUI's High option fails without
  `reasoning-effort-map: "high=xhigh"`, which is now set.
- **The YAML keys exist:** `reasoning-effort`, `reasoning-effort-map`, `thinking-token-budget`, `temp`,
  `top-k`, `top-p`, `min-p`, `presence-penalty`, `chat-template-kwargs`, `reasoning-format`,
  `generation-config`, `override-chat-template`.
- **`rope-scaling: yarn:2` with `max-model-len: 409600` is in force** and the engine had been up for
  an hour: the 400K profile starts and serves. Recall quality at that length is still untested.
- **The n-gram table is in RAM:** startup chose `--ngram-placement ram` automatically (47.68 GiB
  pinned), so this file does not cut RAM by default. The key exists; see section 5.

## 2. What the model and engine support

| Thing | Finding | Source |
|---|---|---|
| Thinking on by default | Yes, `<think>` before the answer | Qwen card |
| Turn thinking off per request | `chat_template_kwargs: {"enable_thinking": false}`; radiance also takes `reasoning_effort: "none"` | Qwen + orcarouter cards; radiance docs (summary) |
| Effort levels | `xhigh` (default), `medium`, `low`, `none`. "high" is not a Qwen3.8 level | Qwen card; radiance docs (summary) |
| Server default effort | radiance `--reasoning-effort`; map with `--reasoning-effort-map high=xhigh` | radiance 1.8.1 docs (summary) — *check for 2.1.0* |
| Thoughts separated | Returned as `reasoning_content`; `usage.completion_tokens_details.reasoning_tokens` counts them | radiance docs (summary) |
| Thinking cap | `thinking_token_budget` per request or `--thinking-token-budget` | radiance docs (summary) |
| Sampling per request | `temperature`, `top_p`, `top_k`, `min_p`, `presence_penalty`, `frequency_penalty`, `repetition_penalty`, `seed`, `stop` | radiance docs (summary) |
| Server sampling defaults | From the model's `generation_config` if the container carries one; unknown for this `.rad` | radiance docs — *check the CONFIGURATION block* |
| Tool calls | Qwen3-Coder XML format; radiance returns `tool_calls` | orcarouter card, radiance docs |

Gotcha: reasoning counts against `max_tokens`. A short limit can leave `content` empty with
`finish_reason: "length"`. Leave max tokens high or unset.

## 3. Sampling

Qwen's recommended values (the only sets published; no separate coding or agent set):

| | temperature | top_p | top_k | min_p | presence_penalty |
|---|---|---|---|---|---|
| Thinking | 1.0 | 0.95 | 20 | 0.0 | 0.0 |
| Non-thinking | 0.7 | 0.80 | 20 | 0.0 | 1.5 |

`presence_penalty` up to 2 reduces endless repetition but can cause language mixing. Neither the
StillDeadcode nor the orcarouter card gives sampling advice for the uncensored file, so use these.

## 4. Open WebUI presets

`flash-next.yml` creates three presets through Open WebUI's API (defined under `webui_presets` of the
`uncensored_v4` entry in `group_vars/llm/main.yml`) and makes **Qwen 3.8 Flash-Next Think** the default (all three carry a "Qwen 3.8" tag):

| Preset | Reasoning effort | Sampling | Max tokens |
|---|---|---|---|
| **Qwen 3.8 Flash-Next Think** (default) | `medium` | none sent (the engine already defaults to the thinking set) | unset |
| **Qwen 3.8 Flash-Next Deep** | `xhigh` | none sent | 32768 |
| **Qwen 3.8 Flash-Next Fast** | `none` (thinking off) | temperature 0.7, top_p 0.8, top_k 20, min_p 0, presence_penalty 1.5 | unset |

All three use native function calling and switch on the Usage capability (the key name is the one
Open WebUI uses as far as I know; if the toggle stays off, switch it on by hand).

- **Edit them in `main.yml`, not the UI.** With `openwebui_presets_update: true` (default) each run
  rewrites them. Set it to `false` to create missing presets only and keep UI edits.
- **They start private to the admin.** To share with family: Workspace → Models → the preset →
  Access. The API call used here does not set access.
- `reasoning_effort` is stored as a free string, so `none` and `xhigh` are accepted even though the
  UI field shows no list. `high` is mapped to `xhigh` by the engine.

## 5. Server-side defaults

Set in `radiance_engine_extra_config` in `group_vars/llm/main.yml`. Applying a change reloads the
model. Already set: `reasoning-effort-map: "high=xhigh"`. Optional, not set:

- `reasoning-effort: medium`: faster answers for every client that sends no effort, including coding
  agents. Qwen warns lower effort does not always shorten an agent task, so I left it off.
- `thinking-token-budget: 8192`: closes the thinking block at N tokens.
- **Less pinned RAM:** change `ngram_placement` in the `uncensored_v4` entry from `""` to `disk`
  (NVMe only; the guide measured about 7x slower on a hard disk). Check the accepted values first:
  `sudo docker exec radiance radiance --help | grep -A3 ngram-placement`. Speed impact is unmeasured.

## 5b. How many long sessions fit

The boot log reports the KV pool in tokens. For `uncensored_v4` with the `long` profile it was
**416,120 tokens ("1.0 sessions at 409600")**, with experts holding 87% of the elastic VRAM. The pool
is shared by token, so it holds one full-length session, or for example one 300K and one 100K session
together, or two 200K ones. A second slot is not wasted: short chats run next to a long one.
Measured pools from Prometheus (`radiance:kv_cache_max_tokens`): stock file 1,100,092 (200K x 8) and
1,130,136 (300K x 4, 3.8 sessions); v4 416,120 (409,600 x 2). The `long` and `xlong` profiles now set
`host_pool_mib: 20480`. In the v4 log the host pool used only 6.57 of its 12 GiB cap, so the engine
may not use the extra; read the `kv cache ... tokens` line after the reload to see. More host pool
means more pinned RAM (up to 2 x the increase) and slower prefill. The earlier stock model on the `card` profile had a 1.1M-token pool. The split between experts
and cache is chosen by the engine; the knob that moves it is `radiance_engine_host_pool_mib`
(more experts in pinned RAM frees VRAM for cache, at the cost of RAM and prefill speed).

The `native` profile (262,144 x 4, no `rope-scaling`, host pool 20480) is the everyday setting: it needs
no YaRN, and the engine sizes the cache to the worst case. Measured with the 20480 host pool: a pool of
976,180 tokens, "3.7 sessions at 262144" (about 93% of the 4 x 262,144 worst case).
Switch to `xlong` only for jobs that need 400K+; a reload takes about a minute.

## 6. Extras worth knowing

- **Usage capability** (Open WebUI model editor): shows token counts, including reasoning tokens.
- **`/v1/messages`, `/v1/responses`:** radiance says it serves the Anthropic Messages and OpenAI
  Responses APIs, so Claude Code and Qwen Code can use it directly. Untested here.
- **Vision and video:** the bf16 vision tower is intact; images and video go in as
  `image_url` / `video_url` parts. Keep Vision on for this model.
- **Structured output:** `response_format` with `json_schema`, useful in scripts.
- **`preserve_thinking`** (default on) keeps earlier turns' thinking in context. Good for agents and
  for prefix-cache hits; it also grows long chats. Turn off per request with
  `chat_template_kwargs: {"preserve_thinking": false}`.
- **Metrics:** `/metrics` carries `vllm:` names (the Grafana dashboard uses these) and `radiance:`
  names, such as `radiance:prefix_hit_cut_tokens_total`. radiance's repo ships its own dashboard
  at `deploy/grafana/radiance.json`.
- **`/server_info`:** reports the effective request defaults and the accepted reasoning levels.

## 7. About "uncensored"

orcarouter's card (self-reported, a rule-based opening-phrase classifier, thinking off) lists
refusal rates falling from about 100% to about 0-3% on AdvBench, JailbreakBench, StrongREJECT and
HarmBench, and from 9.6% to 1.2% over-refusal on XSTest. Capability changes it reports (thinking
off): MMLU 90.0 to 87.7, MMLU-Pro 77.8 to 76.2, GSM8K 92.0 to 93.3. Those numbers are for the
bf16 source, not for the quantized `.rad` served here, and nobody has published a refusal test of
the `.rad` itself. Test it with your own prompts.
