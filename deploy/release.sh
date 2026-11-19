#!/usr/bin/env bash
# Release one version with maintenance mode (platform step 9, docs/platform/09-cd.md §5a).
# Run by the Deploy workflow through Session Manager Run Command (as root); by hand:
#   sudo bash /opt/carlens/repo/deploy/release.sh <tag>
# 1. maintenance on (no new uploads / fresh runs / resumes)  2. wait for working runs (python -m app.maintenance wait)
# 3. deploy.sh <tag>  4. maintenance off, also when a step failed (the app never stays closed)
set -uo pipefail

TAG="${1:?usage: release.sh <tag>}"
DIR="$(cd "$(dirname "$0")" && pwd)"
compose() { docker compose -f "$DIR/docker-compose.prod.yml" "$@"; }
maintenance() { compose exec -T backend python -m app.maintenance "$@"; }

maintenance_off() {
    for _ in $(seq 1 24); do # the new backend needs a few seconds (migrations) before it answers
        maintenance off --by "deploy $TAG" && return 0
        sleep 5
    done
    echo "could not switch maintenance off; by hand: sudo docker compose -f $DIR/docker-compose.prod.yml exec backend python -m app.maintenance off" >&2
    return 1
}

if maintenance on --by "deploy $TAG"; then
    trap maintenance_off EXIT
    maintenance wait
else
    echo "maintenance mode not available in the running version; deploying without waiting"
fi

bash "$DIR/deploy.sh" "$TAG"
