#!/usr/bin/env bash
# Deploy one version on the server (platform stage 8.2, docs/platform/08-2-production-files.md).
#   sudo bash /opt/carlens/repo/deploy/deploy.sh <commit>     rollback = the same with an older commit
# 1. newest deploy/ files (git pull)  2. secrets from Parameter Store -> deploy/.env (root only)
# 3. deploy/ files as they were at <commit> -> /opt/carlens/releases/<commit>/ (hardening V1: a rollback gets the
#    compose file and Caddyfile of its own version, not the newest)  4. Docker signs in to ECR
# 5. pull that commit's images, start / swap the containers from the release folder  6. show their state
set -euo pipefail

TAG="${1:?usage: deploy.sh <git commit of the images>}"
[[ "$TAG" =~ ^[0-9a-f]{7,40}$ ]] || { echo "tag must be a git commit (7-40 hex characters), got '$TAG'" >&2; exit 1; }
REGION="${AWS_REGION:-ap-south-1}"
DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DIR/.." && pwd)"
RELEASES="${CARLENS_RELEASES:-$(cd "$REPO/.." && pwd)/releases}"
KEEP_RELEASES=5
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

# Hardening V1: the deploy files of this version, with the secrets next to them (compose reads .env from there).
REL="$RELEASES/$TAG"
mkdir -p "$RELEASES"
rm -rf "$REL.new"
mkdir "$REL.new"
if git -C "$REPO" cat-file -e "$TAG^{commit}" 2>/dev/null; then
    git -C "$REPO" archive "$TAG" deploy | tar -x -C "$REL.new" --strip-components=1
else
    echo "warning: $TAG is not in git here; using the current deploy files" >&2
    cp -a "$DIR/." "$REL.new/"
fi
install -m 600 .env "$REL.new/.env"
rm -rf "$REL"
mv "$REL.new" "$REL"
touch "$REL"
compose() { docker compose -f "$REL/docker-compose.prod.yml" --project-directory "$REL" "$@"; }

ECR_REGISTRY="$(sed -n "s/^ECR_REGISTRY='\(.*\)'$/\1/p" .env)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null

compose pull --quiet
compose up -d --remove-orphans
docker image prune -af --filter "until=168h" >/dev/null # unused images older than 7 days (disk is 20 GB)
# keep the newest release folders (the one just deployed is the newest)
ls -1dt "$RELEASES"/*/ 2>/dev/null | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf
compose ps
echo "deployed $TAG (deploy files from $REL)"
