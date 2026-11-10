#!/usr/bin/env python3
"""Download a Hugging Face repo snapshot (or selected files) into a directory.

usage: hf_snapshot.py <repo_id> <revision> <dest_dir> [allow_pattern ...]

Writes <dest_dir>/.complete-<revision> on success so Ansible can skip reruns.
The token is read from HF_TOKEN; an empty value means anonymous access.
"""
import os
import sys

from huggingface_hub import snapshot_download


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    repo_id, revision, dest = sys.argv[1:4]
    patterns = sys.argv[4:] or None
    snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=dest,
        allow_patterns=patterns,
        token=os.environ.get("HF_TOKEN") or None,
    )
    with open(os.path.join(dest, f".complete-{revision}"), "w", encoding="utf-8") as marker:
        marker.write(f"{repo_id}@{revision}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
