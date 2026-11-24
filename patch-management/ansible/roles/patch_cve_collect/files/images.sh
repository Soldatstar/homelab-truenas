#!/bin/sh
# One line per running container: image ref, image id, repo digests, container name, compose project,
# compose working directory (where `docker compose` is run to update the stack).
docker ps --format '{{.Image}} {{.ID}} {{.Names}} {{.Label "com.docker.compose.project"}} {{.Label "com.docker.compose.project.working_dir"}}' | while read -r img cid name project workdir; do
  id=$(docker inspect --format '{{.Image}}' "$cid" 2>/dev/null </dev/null)
  digests=$(docker image inspect --format '{{join .RepoDigests ","}}' "$id" 2>/dev/null </dev/null)
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$img" "$id" "$digests" "$name" "$project" "$workdir"
done
