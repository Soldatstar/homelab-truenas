#!/bin/sh
# One line per running container: image ref, image id, repo digests, container name, compose project.
docker ps --format '{{.Image}} {{.ID}} {{.Names}} {{.Label "com.docker.compose.project"}}' | while read -r img cid name project; do
  id=$(docker inspect --format '{{.Image}}' "$cid" 2>/dev/null </dev/null)
  digests=$(docker image inspect --format '{{join .RepoDigests ","}}' "$id" 2>/dev/null </dev/null)
  printf '%s\t%s\t%s\t%s\t%s\n' "$img" "$id" "$digests" "$name" "$project"
done
