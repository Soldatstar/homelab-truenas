#!/bin/sh
# Prints "<image><TAB><status>" for every image a running container uses.
# status: pinned (digest in the reference), current, outdated, unknown (registry not reachable,
# or the running image has no registry digest, e.g. built locally). Best effort: it needs the buildx plugin and registry access.
# $1 (optional): skip containers whose compose project name starts with it.
skip="${1:-}"
docker ps --format '{{.Image}} {{.ID}} {{.Label "com.docker.compose.project"}}' | while read -r img cid project; do
  if [ -n "$skip" ]; then
    case "$project" in "$skip"*) continue ;; esac
  fi
  printf '%s %s\n' "$img" "$cid"
done | sort -u -k1,1 | while read -r img cid; do
  case "$img" in
    *@sha256:*) printf '%s\t%s\n' "$img" pinned; continue ;;
  esac
  # Look up the image the container really runs (by ID): its tag may already point at a newer image.
  id=$(docker inspect --format '{{.Image}}' "$cid" 2>/dev/null </dev/null)
  local_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$id" 2>/dev/null </dev/null)
  # The first "Digest:" line is the top-level manifest. --format is not used: on some hosts it
  # printed the whole manifest list instead of one digest.
  remote=$(docker buildx imagetools inspect "$img" 2>/dev/null </dev/null | sed -n 's/^Digest:[[:space:]]*//p' | head -n 1)
  if [ -z "$remote" ] || [ -z "$local_digests" ]; then
    printf '%s\t%s\n' "$img" unknown
  elif printf '%s' "$local_digests" | grep -q "$remote"; then
    printf '%s\t%s\n' "$img" current
  else
    printf '%s\t%s\n' "$img" outdated
  fi
done
