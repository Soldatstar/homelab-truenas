#!/usr/bin/env python3
"""Simple throughput benchmark for the local LLM endpoint. Standard library only.

  1. decode speed, single stream
  2. decode speed, N concurrent streams (default 2)
  3. prefill: time to first token and prompt tokens/s at long context (cold)

Usage (key from LLM_API_KEY):
  bench.py --base-url http://192.168.1.41:8000 --model qwen3.8-27b
  bench.py --base-url https://llm.viktornote.ch --model qwen3.8-27b --prefill-tokens 32000,120000

Numbers include reasoning tokens. Every prefill prompt carries a fresh nonce,
so the prefix cache cannot flatter the result.
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.request
import uuid

DECODE_PROMPT = ("Write a detailed, well-structured essay of about 600 words on the history "
                 "of the Gotthard railway tunnel.")


def stream(base_url, key, body, timeout):
    """Return dict(ttft, total, prompt_tokens, completion_tokens)."""
    body = dict(body, stream=True, stream_options={"include_usage": True})
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    start = time.monotonic()
    ttft, usage = None, {}
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        for line in resp:
            line = line.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            chunk = json.loads(line[5:])
            if chunk.get("usage"):
                usage = chunk["usage"]
            if ttft is None and chunk.get("choices"):
                delta = chunk["choices"][0].get("delta", {})
                if any(delta.get(k) for k in ("content", "reasoning_content", "reasoning")):
                    ttft = time.monotonic() - start
    total = time.monotonic() - start
    return {
        "ttft": ttft if ttft is not None else total,
        "total": total,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }


def decode_run(args, key, streams):
    body = {"model": args.model, "max_tokens": args.max_tokens,
            "messages": [{"role": "user", "content": DECODE_PROMPT}]}
    results, errors = [], []

    def worker():
        try:
            results.append(stream(args.base_url, key, body, args.timeout))
        except Exception as err:  # noqa: BLE001
            errors.append(str(err))

    threads = [threading.Thread(target=worker) for _ in range(streams)]
    start = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = time.monotonic() - start
    if errors:
        print(f"  {streams} stream(s): FAILED: {errors[0]}")
        return
    per_stream = [r["completion_tokens"] / max(r["total"] - r["ttft"], 1e-6) for r in results]
    aggregate = sum(r["completion_tokens"] for r in results) / wall
    print(f"  {streams} stream(s): {sum(per_stream) / len(per_stream):6.1f} tok/s per stream, "
          f"{aggregate:6.1f} tok/s aggregate, TTFT {max(r['ttft'] for r in results):.2f}s")


def prefill_run(args, key, target_tokens):
    lines = max(1, target_tokens // 16)
    prompt = f"Log export {uuid.uuid4().hex}\n" + "".join(
        f"Item {i}: sku {i * 7919 % 100000:05d}, quantity {i % 97}, warehouse W{i % 13}\n" for i in range(lines)
    ) + "\nReply with the single word OK."
    body = {"model": args.model, "max_tokens": 16, "messages": [{"role": "user", "content": prompt}]}
    try:
        result = stream(args.base_url, key, body, args.timeout)
    except Exception as err:  # noqa: BLE001
        print(f"  ~{target_tokens} tokens: FAILED: {err}")
        return
    rate = result["prompt_tokens"] / max(result["ttft"], 1e-6)
    print(f"  {result['prompt_tokens']:>7} prompt tokens: TTFT {result['ttft']:7.2f}s, {rate:8.0f} prompt tok/s")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="no /v1 suffix")
    parser.add_argument("--model", required=True)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--prefill-tokens", default="32000,100000", help="comma-separated prompt sizes; empty to skip")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    key = os.environ.get("LLM_API_KEY", "")
    if not key:
        print("LLM_API_KEY is not set", file=sys.stderr)
        return 2

    print("Decode throughput")
    decode_run(args, key, 1)
    if args.concurrency > 1:
        decode_run(args, key, args.concurrency)
    sizes = [int(s) for s in args.prefill_tokens.split(",") if s.strip()]
    if sizes:
        print("Cold prefill")
        for size in sizes:
            prefill_run(args, key, size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
