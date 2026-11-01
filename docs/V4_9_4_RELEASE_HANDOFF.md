# V4.9.4 Immutable Release & Recovery Handoff

The November 1, 2026 task authorized one unattended release, conditional on all verification gates passing. Its committed scope is `deploy/authorizations/v494-once.json` and its deployment helper is `deploy/staging_v494.py`. No additional routine human approval is required for this release. Future distinct releases require new explicit user authorization.

All source changes originate locally on `feature/autotrader-v46-intelligent-opportunity-engine`. The `main` branch, financial database histories, and unrelated applications remain untouched.

---

## 1. Release Identity & Artifact Provenance

* **Release Tag:** `v4.9.4-rc.1`
* **Release Commit:** `a71db8bcea94d018a77d60ed7d6937369a6105c4`
* **Source Archive:** `autotrader-4.9.4rc1-a71db8bcea94.tar.gz`
  * SHA256: `9807e77b1a7b50af04e60ea352c5bea7997f59b514a792a32844d4b7117df128`
* **Source Fingerprint:** `76121235ff5442c35ef3d3198e706e5bf1fd185b470b676247f8ddbd49f9a537`
* **Verified Images Archive:** `verified-images-a71db8bcea94.tar.gz`
  * SHA256: `75e90d7fb25ea9b9c59a8fd2b78f2f89add4814503dd857ebaa009653f505c22`
* **Canonical Loaded Image IDs (Linux/AMD64):**
  * App / Worker: `sha256:bf44a12844a92fc66777cdec3eae78f287c7c39d4d09133e38ec62a354528aa2`
  * Frontend: `sha256:b227e16398caf365bbe173eb887a5fadbef7a9d212ccb89141165404944d0296`

---

## 2. Deployment Scope & Authorization Record

* **Target Host:** Aruba VPS SSH alias `aruba-vps`
* **Staging Directory:** `/opt/personal-plan/staging`
* **Compose Project:** `autotrader-aruba-test`
* **Loopback Ports:** Backend `127.0.0.1:18000`, Frontend `127.0.0.1:13000`
* **Operating Mode:** Strictly SIMULATED / PAPER ONLY (`live_trading_authorized: false`, real orders disabled)
* **Single-Task Authorization Claim:**
  * File: `/opt/personal-plan/staging/ops/authorization-autotrader-v494-2026-11-01.json`
  * Task ID: `autotrader-v494-2026-11-01`
  * Request SHA256: `cf63f563c870f03a91da03e12086ee2a896b58914423510c9a0361577db746ab`
  * Claim Status: **CLAIMED and IMMUTABLE** (Cannot be reused by any other release or commit)

---

## 3. Financial State & Preservation Proof

* **Primary Account:** `PERSONAL_PLAN_PAPER_7000`
  * Initial Funding: €7,000.00
  * Current Cash: €6,936.84
  * Available Cash: €6,936.84
  * Open Exposure: €0.00 (Flat)
  * Realized P&L: −€63.16
  * Closed Positions: 10
  * Open Positions: 0
  * Pending Orders: 0
  * Risk State: `HEALTHY`, Control: `RUNNING`
* **Shadow Accounts:** All 15 shadow portfolios (€500 initial each) + staging database preserved.
* **Pre-Cutover Backup:** `/opt/personal-plan/staging/backups/20261101T165217Z-1bb6d946/backup-set.json`
* **Post-Cutover Backup:** `/opt/personal-plan/staging/backups/20261101T170154Z-7575a4e1/backup-set.json` (522,703,255 dump bytes)
* **Table Seal Audit:** All 170 financial table seals matched 100% across the cutover (`status: "PASS"`).

---

## 4. Live Runtime Health & Verification Facts

Verified via `deploy/staging_v494.py verify`:
* `backend-1`: Healthy (`127.0.0.1:18000`)
* `frontend-1`: Healthy (`127.0.0.1:13000`)
* `worker-1`: Healthy (Scan & Monitor active)
* `research-worker-1`: Running
* `postgres-1`: Healthy
* `redis-1`: Healthy
* `curl http://127.0.0.1:18000/healthz` -> `{"status":"ok","mode":"paper","version":"4.9.4-rc.1"}`
* `curl http://127.0.0.1:18000/readyz` -> `{"ready":true,"live_trading_enabled":false}`
* `curl -I http://127.0.0.1:13000/` -> `HTTP/1.1 200 OK`

---

## 5. Rollback Runbook (In Case of Degradation)

If an unrecoverable runtime issue occurs, follow this strictly bounded procedure:

### Step 1: Pause Trading Immediately
```bash
ssh aruba-vps 'curl -s -X POST http://127.0.0.1:18000/api/personal-paper/control/pause'
```

### Step 2: Confirm Portfolios are Flat
Verify no positions are open before changing container versions:
```bash
ssh aruba-vps 'curl -s http://127.0.0.1:18000/api/personal-paper | jq .portfolio.positions'
```
*If positions are open, do NOT kill containers; let protective stops manage exits or wait until flat.*

### Step 3: Switch Image Tags in Compose File
The pre-cutover Compose configuration is preserved at:
`/opt/personal-plan/staging/evidence/v494-a71db8bcea94/previous-compose`
To roll back container images to the previous tested release (V4.9.2 / commit `1c1b758`):
```bash
ssh aruba-vps
cd /opt/personal-plan/staging
cp evidence/v494-a71db8bcea94/previous-compose docker-compose.yml
docker compose up -d --no-recreate
```

### Step 4: Verify Rolled Back Health
```bash
curl -s http://127.0.0.1:18000/healthz
curl -s http://127.0.0.1:18000/readyz
```

### Safety Rules During Recovery
1. **Never run `docker compose down -v`:** This will destroy the persistent PostgreSQL and Redis volumes.
2. **Never run global `docker system prune -a`:** This deletes cached rollback images.
3. **Never restore old database dumps over newer transactions:** Use backups only for disaster recovery where database corruption has been conclusively demonstrated.
4. **Any source corrections must originate locally:** Implement, test, commit, and push on `feature/autotrader-v46-intelligent-opportunity-engine`, then request a new task authorization.
