#!/bin/bash
# Pull-mode deploy for the beta t4g server: pull the prebuilt arm64 image from ECR and restart.
# NOT yet wired in. Prereqs: docker on the instance, and RenderhausBetaWebRole needs ECR read
# (ecr:GetAuthorizationToken on *, ecr:BatchGetImage/GetDownloadUrlForLayer/BatchCheckLayerAvailability on the repo).
# Usage (as root on the instance): deploy-pull.sh [tag]   (default: staging; pass a 7-char SHA to pin/rollback)
set -euo pipefail
TAG=${1:-staging}; REGION=us-east-1; ACCOUNT=648597472910
REG=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com; IMG=$REG/renderhaus-agent:$TAG
DATA=/srv/renderhaus/data; ENVF=/run/renderhaus/env
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REG >/dev/null
docker pull -q "$IMG"
/usr/local/sbin/renderhaus-fetch-env
mkdir -p $DATA; chown 10001:10001 $DATA
docker network inspect renderhaus >/dev/null 2>&1 || docker network create renderhaus >/dev/null
docker rm -f renderhaus-api renderhaus-studio >/dev/null 2>&1 || true
# Ports bind to localhost only; nginx stays the public entry point (same upstreams as the systemd units).
docker run -d --name renderhaus-api --restart=always --network renderhaus --network-alias api \
  --env-file $ENVF -v $DATA:$DATA -p 127.0.0.1:8000:8000 --security-opt seccomp=unconfined "$IMG"
docker run -d --name renderhaus-studio --restart=always --network renderhaus \
  --env-file $ENVF -e NODE_ENV=production -e STUDIO_API_ORIGIN=http://api:8000 -p 127.0.0.1:5174:5174 \
  -w /srv/renderhaus/current/studio "$IMG" npx next start --port 5174 --hostname ::
sleep 10
curl -fsS -o /dev/null -w 'api %{http_code}\n' http://127.0.0.1:8000/api/health || true
curl -fsS -o /dev/null -w 'studio %{http_code}\n' http://127.0.0.1:5174/ || true
docker image prune -f >/dev/null
