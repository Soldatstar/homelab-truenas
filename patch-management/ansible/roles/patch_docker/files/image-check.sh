#!/bin/sh
# Prints "<image><TAB><status>" for every image a running container uses.
# status: pinned (digest in the reference), current, outdated, unknown (registry not reachable
# or the image has no tag). Best effort: it needs the buildx plugin and registry access.
docker ps --format '{{.Image}}' | sort -u | while read -r img; do
  case "$img" in
    *@sha256:*) printf '%s\t%s\n' "$img" pinned; continue ;;
  esac
  local_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$img" 2>/dev/null)
  remote=$(docker buildx imagetools inspect "$img" --format '{{.Manifest.Digest}}' 2>/dev/null)
  if [ -z "$remote" ] || [ -z "$local_digests" ]; then
    printf '%s\t%s\n' "$img" unknown
  elif printf '%s' "$local_digests" | grep -q "$remote"; then
    printf '%s\t%s\n' "$img" current
  else
    printf '%s\t%s\n' "$img" outdated
  fi
done
