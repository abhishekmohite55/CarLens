#!/usr/bin/env bash
# Nightly database backup (platform stage 8.2): pg_dump of Supabase -> gzip -> s3://<bucket>/backups/pg/<date>.sql.gz
# The S3 lifecycle rule deletes backups after 14 days. The connection also counts as activity (Supabase pauses a
# free project after 7 days without any). Run by cron as root (deploy/carlens.cron); by hand: sudo bash backup.sh
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
DIR="$(cd "$(dirname "$0")" && pwd)"
value() { sed -n "s/^$1='\(.*\)'$/\1/p" "$DIR/.env"; }
DB="$(value DATABASE_URL)"
BUCKET="$(value S3_BUCKET)"
[[ -n "$DB" && -n "$BUCKET" ]] || { echo "DATABASE_URL or S3_BUCKET missing in $DIR/.env (run deploy.sh first)" >&2; exit 1; }

day="$(date -u +%F)"
out="$(mktemp --suffix=.sql.gz)"
trap 'rm -f "$out"' EXIT
# pg_dump 17 = Supabase's major version; the URL goes in as an environment variable, not on the command line
DB="$DB" docker run --rm -e DB postgres:17 sh -c 'pg_dump --no-owner --no-privileges --schema=public "$DB"' \
    | gzip > "$out"
aws s3 cp --region "$REGION" --only-show-errors "$out" "s3://$BUCKET/backups/pg/$day.sql.gz"
echo "$(date -u +%FT%TZ) backup $day.sql.gz $(du -h "$out" | cut -f1)"
