# Personal Plan on the Mac

This local host uses RC2 with the tested worker-health correction recorded in the validation report, native ARM64 images and the isolated Compose project `autotrader-v46-mac`. It has a new persistent EUR500 simulated account, independent PostgreSQL/Redis/research/report volumes, generated local credentials and public market data. No VPS access, imported financial history, new strategy approval or real orders are involved. RC2's immutable tag and production-blocked release evidence stay unchanged.

## Access and credentials

- Frontend: <http://localhost:3000>.
- Backend: <http://localhost:8000> (loopback only).
- LAN frontend: use `http://MAC_LAN_IP:3000`, with the private address recorded in `.env.local`.
- Sign in as the `DASHBOARD_USERNAME` stored in `.env.local`; the generated `DASHBOARD_PASSWORD` is in that same private mode-0600 file. Do not paste it into logs, chat or Git.

The frontend forwards authenticated API requests to the backend. Its local Nginx configuration permits private network clients only. PostgreSQL, Redis and worker endpoints have no host/LAN port publications. LAN HTTP is intended for the trusted local network; no public domain, forwarding, DNS or firewall changes are configured. A second physical device must independently confirm reachability. If DHCP changes the Mac's IP, update `MAC_LAN_IP` in the private environment file and recreate only the frontend; localhost remains available.

## Operating commands

Run from this repository. These commands target only the Mac project:

```sh
docker compose -p autotrader-v46-mac --env-file .env.local \
  -f docker-compose.yml -f docker-compose.mac.yml --profile research ps

docker compose -p autotrader-v46-mac --env-file .env.local \
  -f docker-compose.yml -f docker-compose.mac.yml --profile research \
  up -d --wait --no-build backend worker frontend research-worker

docker compose -p autotrader-v46-mac --env-file .env.local \
  -f docker-compose.yml -f docker-compose.mac.yml logs --tail 100 worker
```

Normal starts retain every financial record and do not reset funding. Do not use the fresh-deployment `deploy/vps.py up` helper for this populated server: it intentionally refuses populated databases. Do not use `down -v`, global prune or broad resource removal. Stop the Mac project's application services explicitly when needed; retain its volumes and images.

Initial setup generated `.env.local` without overwriting an existing file, built the backend/frontend/Redis using the Mac's native architecture, used native PostgreSQL 16, ran the existing Alembic migration command and research-volume seeder, then started the application and research worker. Existing local research was copied as immutable research evidence; old account financial histories were not imported. The standard PostgreSQL image avoids rebuilding the version-specific Alpine backport in the VPS image recipe. The Mac override leaves the production Compose file and its protections unchanged.

All long-running containers use `restart: unless-stopped`; they continue independently of terminals and return when Docker's engine returns. Docker Desktop must be running and the Mac awake. Existing power settings were inspected, not changed: AC system sleep is disabled; battery sleep can interrupt service. Closing the lid, rebooting, quitting Docker, changing networks or losing internet can interrupt observations. Whole-machine reboot/Docker Desktop restart and another physical LAN device are not simulated by application-container restart tests.

## Verification and evidence

See [Mac validation report](V4_6_MAC_VALIDATION.md) and [dated evidence](evidence/v4_6_mac_20261026). Automated financial and destructive UI tests use separate disposable databases/services. The persistent server receives read-only browser/API reviews and controlled restart/persistence checks. Synthetic paper fills are marked separately from actual public-market observations. No short observation window establishes profitability or a completed 30-day result.

Source changes remain on `feature/autotrader-v46-intelligent-opportunity-engine`; no new release tag is created. Changes to the local hosting files do not authorize VPS deployment.
