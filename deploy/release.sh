#!/usr/bin/env bash
# Release one version with maintenance mode and a health check (platform step 9, docs/platform/09-cd.md §5a, §8).
# Run by the Deploy workflow through Session Manager Run Command (as root); by hand:
#   sudo bash /opt/carlens/repo/deploy/release.sh <tag>
# 1. maintenance on (no new uploads / fresh runs / resumes)  2. wait for working runs (python -m app.maintenance wait)
# 3. deploy.sh <tag>  4. health check (90 s): not healthy -> deploy the version that ran before, exit 1
# 5. maintenance off, also when a step failed (the app never stays closed; it also expires by itself, auto_off_min)
set -uo pipefail

TAG="${1:?usage: release.sh <tag>}"
DIR="$(cd "$(dirname "$0")" && pwd)"
HEALTH_WAIT_SEC=90
compose() { docker compose -f "$DIR/docker-compose.prod.yml" "$@"; }
maintenance() { compose exec -T backend python -m app.maintenance "$@"; }
healthy() { compose exec -T backend python -m app.health --url http://127.0.0.1:8000/api/health --wait "$HEALTH_WAIT_SEC"; }

maintenance_off() {
    for _ in $(seq 1 24); do # the new backend needs a few seconds (migrations) before it answers
        maintenance off --by "deploy $TAG" && return 0
        sleep 5
    done
    echo "could not switch maintenance off (it expires by itself after maintenance.auto_off_min); by hand: sudo docker compose -f $DIR/docker-compose.prod.yml exec backend python -m app.maintenance off" >&2
    return 1
}

PREVIOUS="$(sed -n "s/^TAG='\(.*\)'$/\1/p" "$DIR/.env" 2>/dev/null || true)"
echo "running now: ${PREVIOUS:-none}; deploying: $TAG"

if maintenance on --by "deploy $TAG"; then
    trap maintenance_off EXIT
    maintenance wait
else
    echo "maintenance mode not available in the running version; deploying without waiting"
fi

if ! bash "$DIR/deploy.sh" "$TAG"; then
    echo "deploy.sh failed for $TAG" >&2
    exit 1
fi

if healthy; then
    echo "released $TAG"
    exit 0
fi

echo "$TAG is not healthy" >&2
compose logs --tail 40 backend >&2
if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$TAG" ]; then
    echo "rolling back to $PREVIOUS" >&2
    bash "$DIR/deploy.sh" "$PREVIOUS" && healthy && echo "rolled back to $PREVIOUS (healthy)" >&2
fi
exit 1
