# deploy/ — the production server (platform stage 8.2)

Used only on the EC2 server; the laptop keeps `docker-compose.yml`. Step by step: `docs/platform/08-aws-runbook.md` (not in git).

| File | What it is |
|---|---|
| `docker-compose.prod.yml` | caddy + frontend + backend, images from ECR tagged with the git commit |
| `Caddyfile` | HTTPS certificate for the DuckDNS name; only CloudFront (secret header) gets through |
| `deploy.sh <commit>` | secrets from Parameter Store → `.env`; copies `deploy/` as it was at that commit to `/opt/carlens/releases/<commit>/` and starts from there (newest 5 kept), so an older commit = a full rollback (images + compose file + Caddyfile) |
| `release.sh <commit>` | what the Deploy workflow runs: maintenance on, wait, `deploy.sh`, backend health + app page through Caddy, automatic rollback, maintenance off |
| `backup.sh` | nightly `pg_dump` of Supabase → S3 `backups/pg/` |
| `carlens.cron` | nightly backup + run-folder prune; copy to `/etc/cron.d/carlens` |
| `viewer-ip.js` | CloudFront Function: visitor address → `X-Viewer-IP` |
| `example.env` | names of the `.env` values (dummy), for the laptop check |

On the server (as root):

```
bash /opt/carlens/repo/deploy/deploy.sh <commit>                  # deploy / rollback
bash /opt/carlens/repo/deploy/backup.sh                           # backup now
docker compose -f /opt/carlens/repo/deploy/docker-compose.prod.yml logs -f backend
docker compose -f /opt/carlens/repo/deploy/docker-compose.prod.yml ps
```

`exec`, `logs` and `ps` work with either compose file (same project name `carlens`); the running containers were started from `/opt/carlens/releases/<commit>/`.
