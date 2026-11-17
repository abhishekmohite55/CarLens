#!/usr/bin/env bash
# Deploy one version on the server (platform stage 8.2, docs/platform/08-2-production-files.md).
#   sudo bash /opt/carlens/repo/deploy/deploy.sh <commit>     rollback = the same with an older commit
# 1. newest deploy/ files (git pull)  2. secrets from Parameter Store -> deploy/.env (root only)
# 3. Docker signs in to ECR  4. pull that commit's images, start / swap the containers  5. show their state
set -euo pipefail

TAG="${1:?usage: deploy.sh <git commit of the images>}"
REGION="${AWS_REGION:-ap-south-1}"
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

git -C "$DIR/.." pull --ff-only --quiet

# Secrets: /carlens/prod/NAME -> NAME='value'. Values are never printed. Single quotes keep $ and % literal.
umask 077
tmp="$(mktemp "$DIR/.env.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
aws ssm get-parameters-by-path --region "$REGION" --path /carlens/prod/ --recursive --with-decryption \
    --query 'Parameters[*].[Name,Value]' --output text |
while IFS=$'\t' read -r name value; do
    if [[ "$value" == *"'"* ]]; then
        echo "parameter ${name##*/} contains a single quote; change it in Parameter Store" >&2
        exit 1
    fi
    printf "%s='%s'\n" "${name##*/}" "$value"
done > "$tmp"
for need in DATABASE_URL ECR_REGISTRY ORIGIN_HOST ORIGIN_SECRET S3_BUCKET; do
    grep -q "^$need=" "$tmp" || { echo "/carlens/prod/$need is missing in Parameter Store" >&2; exit 1; }
done
echo "TAG='$TAG'" >> "$tmp"
mv "$tmp" .env
trap - EXIT

ECR_REGISTRY="$(sed -n "s/^ECR_REGISTRY='\(.*\)'$/\1/p" .env)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null

docker compose -f docker-compose.prod.yml pull --quiet
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker image prune -af --filter "until=168h" >/dev/null # unused images older than 7 days (disk is 20 GB)
docker compose -f docker-compose.prod.yml ps
echo "deployed $TAG"
