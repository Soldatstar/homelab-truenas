#!/bin/sh
# Resolve an image tag to its digest without Docker (needs curl).
#   resolve-digest.sh magiccodingman/vllm-radiance 1.0.387
#   resolve-digest.sh ghcr.io/open-webui/open-webui v0.13.3
#   resolve-digest.sh library/postgres 17
set -eu

image="${1:?usage: resolve-digest.sh <image> <tag>}"
tag="${2:?usage: resolve-digest.sh <image> <tag>}"
accept='Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json'

case "$image" in
    ghcr.io/*)
        repo="${image#ghcr.io/}"
        token_url="https://ghcr.io/token?scope=repository:${repo}:pull"
        registry="https://ghcr.io"
        ;;
    *)
        repo="${image#docker.io/}"
        token_url="https://auth.docker.io/token?service=registry.docker.io&scope=repository:${repo}:pull"
        registry="https://registry-1.docker.io"
        ;;
esac

token=$(curl -fsS "$token_url" | sed 's/.*"token":"\([^"]*\)".*/\1/')
digest=$(curl -fsSI -H "Authorization: Bearer $token" -H "$accept" "$registry/v2/$repo/manifests/$tag" \
    | tr -d '\r' | awk 'tolower($1) == "docker-content-digest:" {print $2}')
[ -n "$digest" ] || { echo "no digest found for $image:$tag" >&2; exit 1; }
echo "${image}@${digest}"
