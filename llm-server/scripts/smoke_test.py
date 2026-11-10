#!/usr/bin/env python3
"""Smoke test for the local LLM endpoint. Standard library only.

Checks: health, model list (name + aliases), chat completion, OpenAI tool
call, two concurrent requests, a full Anthropic /v1/messages tool round trip
(what Claude Code does), and prefix caching (same long prefix twice).

The API key is read from LLM_API_KEY. Exit code 0 only if every check passes.
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

RESULTS = []

WEATHER_OPENAI = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
}
WEATHER_ANTHROPIC = {
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "input_schema": WEATHER_OPENAI["function"]["parameters"],
}


class Client:
    def __init__(self, base_url, key, timeout):
        self.base = base_url.rstrip("/")
        self.key = key
        self.timeout = timeout

    def _request(self, method, path, body=None):
        headers = {
            "Authorization": f"Bearer {self.key}",
            "x-api-key": self.key,
            "anthropic-version": "2023-06-01",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(self.base + path, data=data, headers=headers, method=method)

    def call(self, method, path, body=None):
        try:
            with urllib.request.urlopen(self._request(method, path, body), timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"HTTP {err.code} from {path}: {err.read().decode()[:500]}") from err
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def stream_chat(self, body):
        """Return (seconds to first streamed delta, usage dict or None)."""
        body = dict(body, stream=True, stream_options={"include_usage": True})
        start = time.monotonic()
        ttft, usage = None, None
        with urllib.request.urlopen(self._request("POST", "/v1/chat/completions", body), timeout=self.timeout) as resp:
            for line in resp:
                line = line.decode().strip()
                if not line.startswith("data:") or line.endswith("[DONE]"):
                    continue
                chunk = json.loads(line[5:])
                if chunk.get("usage"):
                    usage = chunk["usage"]
                if ttft is None and chunk.get("choices"):
                    delta = chunk["choices"][0].get("delta", {})
                    if any(delta.get(k) for k in ("content", "reasoning_content", "reasoning", "tool_calls")):
                        ttft = time.monotonic() - start
        return ttft, usage

    def metric_sum(self, fragment):
        text = self.call("GET", "/metrics")
        total, found = 0.0, False
        for line in str(text).splitlines():
            if line.startswith("#") or fragment not in line.split(" ")[0]:
                continue
            if "_created" in line.split(" ")[0]:
                continue
            try:
                total += float(line.rsplit(" ", 1)[1])
                found = True
            except (ValueError, IndexError):
                pass
        return total if found else None


def check(name):
    def wrap(func):
        def run(*args, **kwargs):
            start = time.monotonic()
            try:
                detail = func(*args, **kwargs)
                RESULTS.append((name, True, detail, time.monotonic() - start))
            except Exception as err:  # noqa: BLE001 - report every failure, keep going
                RESULTS.append((name, False, f"{type(err).__name__}: {err}", time.monotonic() - start))
        return run
    return wrap


def chat_text(client, model, prompt, max_tokens=4096):
    resp = client.call("POST", "/v1/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    })
    return (resp["choices"][0]["message"].get("content") or "").strip()


@check("health")
def test_health(client):
    client.call("GET", "/health")
    return "ok"


@check("models")
def test_models(client, expected):
    ids = [m["id"] for m in client.call("GET", "/v1/models")["data"]]
    missing = [name for name in expected if name not in ids]
    if missing:
        raise RuntimeError(f"missing served names {missing}; server lists {ids}")
    return ", ".join(ids)


@check("chat completion")
def test_chat(client, model):
    text = chat_text(client, model, "What is 17 + 25? Reply with the number only.")
    if "42" not in text:
        raise RuntimeError(
            f"expected 42, got {text[:200]!r}. Garbled output right after a weight-format "
            "change points at the MXFP4 path: see the FP8 fallback in docs/troubleshooting.md"
        )
    return text[:60]


@check("openai tool call")
def test_tool_call(client, model):
    resp = client.call("POST", "/v1/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": "What is the weather in Zurich right now? Use the tool."}],
        "tools": [WEATHER_OPENAI],
        "tool_choice": "auto",
        "max_tokens": 4096,
    })
    calls = resp["choices"][0]["message"].get("tool_calls") or []
    if not calls:
        raise RuntimeError(f"no tool_calls in response: {json.dumps(resp['choices'][0]['message'])[:400]}")
    args = json.loads(calls[0]["function"]["arguments"])
    if calls[0]["function"]["name"] != "get_weather" or "city" not in args:
        raise RuntimeError(f"unexpected tool call: {calls[0]}")
    return f"get_weather({args})"


@check("2 concurrent requests")
def test_concurrent(client, model):
    answers, errors = {}, []

    def worker(index, a, b):
        try:
            answers[index] = (chat_text(client, model, f"What is {a} + {b}? Reply with the number only."), a + b)
        except Exception as err:  # noqa: BLE001
            errors.append(str(err))

    threads = [threading.Thread(target=worker, args=(i, 100 + i, 23)) for i in range(2)]
    start = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise RuntimeError("; ".join(errors))
    for text, expected in answers.values():
        if str(expected) not in text:
            raise RuntimeError(f"expected {expected}, got {text[:100]!r}")
    return f"both correct in {time.monotonic() - start:.1f}s"


@check("anthropic /v1/messages tool round trip")
def test_messages_round_trip(client, model):
    question = {"role": "user", "content": "What is the weather in Zurich right now? Use the get_weather tool."}
    base = {"model": model, "max_tokens": 4096, "tools": [WEATHER_ANTHROPIC]}
    first = client.call("POST", "/v1/messages", dict(base, messages=[question]))
    if not isinstance(first, dict) or first.get("type") != "message":
        raise RuntimeError(f"not an Anthropic message response: {str(first)[:300]}")
    uses = [b for b in first.get("content", []) if b.get("type") == "tool_use"]
    if not uses or uses[0].get("name") != "get_weather" or first.get("stop_reason") != "tool_use":
        raise RuntimeError(f"no tool_use block (stop_reason={first.get('stop_reason')}): {json.dumps(first)[:400]}")
    replay = [b for b in first["content"] if b.get("type") in ("text", "tool_use")]
    result = {
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": uses[0]["id"],
            "content": json.dumps({"temperature_c": 7, "condition": "fog"}),
        }],
    }
    second = client.call("POST", "/v1/messages", dict(
        base, messages=[question, {"role": "assistant", "content": replay}, result]))
    text = " ".join(b.get("text", "") for b in second.get("content", []) if b.get("type") == "text")
    if "7" not in text:
        raise RuntimeError(f"final answer does not use the tool result: {text[:300]!r}")
    return f"tool_use({uses[0].get('input')}) -> {text.strip()[:70]!r}"


@check("prefix cache (same long prefix twice)")
def test_prefix_cache(client, model, lines):
    nonce = uuid.uuid4().hex
    prefix = f"Inventory export {nonce}\n" + "".join(
        f"Item {i}: sku {i * 7919 % 100000:05d}, quantity {i % 97}, warehouse W{i % 13}\n" for i in range(lines)
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prefix + "\nReply with the single word OK."}],
        "max_tokens": 32,
    }
    hits_before = client.metric_sum("prefix_cache_hits")
    cold, usage = client.stream_chat(body)
    warm, usage_warm = client.stream_chat(body)
    hits_after = client.metric_sum("prefix_cache_hits")
    if cold is None or warm is None:
        raise RuntimeError("the server streamed no tokens for the prefix probe")
    prompt_tokens = (usage or {}).get("prompt_tokens", 0)
    cached = ((usage_warm or {}).get("prompt_tokens_details") or {}).get("cached_tokens")
    hit_delta = None if hits_before is None or hits_after is None else hits_after - hits_before
    detail = (f"prompt {prompt_tokens} tok, TTFT cold {cold:.2f}s -> warm {warm:.2f}s "
              f"({cold / warm:.1f}x), cached_tokens={cached}, cache-hit metric +{hit_delta}")
    hit = (hit_delta or 0) >= prompt_tokens * 0.5 or (cached or 0) >= prompt_tokens * 0.5
    if not hit and warm > cold * 0.5:
        raise RuntimeError("no prefix reuse detected: " + detail)
    if prompt_tokens < 15000:
        detail += " [warning: prefix shorter than 15k tokens, raise --prefix-lines]"
    return detail


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="e.g. http://192.168.1.41:8000 (no /v1)")
    parser.add_argument("--model", required=True)
    parser.add_argument("--alias", action="append", default=[], help="additional served name, repeatable")
    parser.add_argument("--messages-base-url", help="Anthropic endpoint if different (LiteLLM)")
    parser.add_argument("--messages-key-env", default="LLM_API_KEY")
    parser.add_argument("--prefix-lines", type=int, default=1300, help="about 16 tokens per line")
    parser.add_argument("--skip-prefix-cache", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    key = os.environ.get("LLM_API_KEY", "")
    if not key:
        print("LLM_API_KEY is not set", file=sys.stderr)
        return 2
    client = Client(args.base_url, key, args.timeout)
    messages_client = Client(args.messages_base_url or args.base_url,
                             os.environ.get(args.messages_key_env, key), args.timeout)
    messages_model = args.alias[0] if args.alias and not args.messages_base_url else args.model

    test_health(client)
    test_models(client, [args.model] + args.alias)
    test_chat(client, args.model)
    test_tool_call(client, args.model)
    test_concurrent(client, args.model)
    test_messages_round_trip(messages_client, messages_model)
    if not args.skip_prefix_cache:
        test_prefix_cache(client, args.model, args.prefix_lines)
    preemptions = None
    try:
        preemptions = client.metric_sum("num_preemptions")
    except Exception:  # noqa: BLE001 - informational only
        pass

    failed = 0
    for name, ok, detail, seconds in RESULTS:
        failed += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name} ({seconds:.1f}s): {detail}")
    print(f"preemptions since start: {preemptions}")
    print(f"{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
