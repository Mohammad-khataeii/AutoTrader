# V4.9.5 Immutable Release & Recovery Handoff

The November 1, 2026 task authorized one unattended release, conditional on all verification gates passing. Its committed scope is `deploy/authorizations/v495-once.json` and its deployment helper is `deploy/staging_v495.py`. No additional routine human approval is required for this release. Future distinct releases require new explicit user authorization.

All source changes originate locally on `feature/autotrader-v46-intelligent-opportunity-engine`. The `main` branch, financial database histories, and unrelated applications remain untouched.

---

## 1. Release Identity & Artifact Provenance

* **Release Tag:** `v4.9.5-rc.2`
* **Release Commit:** `40c72988a11e0488895e131340837f7bc7dc21d0`
* **Source Archive:** `autotrader-4.9.5rc1-40c72988a11e.tar.gz`
  * SHA256: `c258d95158830fef75ebc5daeaa39e9cc977fbc7b5393ca72ad459f1bedaabde`
* **Source Fingerprint:** `85a3158717bbd4d52788de3640442e32ff1d8df17bcd92512d5ed9d6d2e701ff`
* **Verified Images Archive:** `verified-images-40c72988a11e.tar.gz`
  * SHA256: `b0d1b4634e258127f0d146113b701553da8253c7cb6104eff6bac6d7c7918136`
* **Canonical Loaded Image IDs (Linux/AMD64):**
  * App / Worker / Backend: `sha256:e740cb055b0c51b9150e6e4d28796bb81b749b7c828db2ba5f99494fe3c4e458`
  * Frontend: `sha256:f02293dc89e5c6147b56555abc912ffff3c1fb5c57c6a7250d048195d8b232e1`

---

## 2. Deployment Scope & Authorization Record

* **Target Host:** Aruba VPS SSH alias `aruba-vps`
* **Staging Directory:** `/opt/personal-plan/staging`
* **Compose Project:** `autotrader-aruba-test`
* **Loopback Ports:** Backend `127.0.0.1:18000`, Frontend `127.0.0.1:13000`
* **Operating Mode:** Strictly SIMULATED / PAPER ONLY (`live_trading_authorized: false`, real orders disabled)
* **Single-Task Authorization Claim:**
  * File: `/opt/personal-plan/staging/ops/authorization-autotrader-v495-2026-11-01.json`
  * Task ID: `autotrader-v495-2026-11-01`
  * Request SHA256: `c5cff24252b11f61d6684ca7cb1389c7b76ae69f7b58f69da76a6dd10746231f`
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
* **Pre-Cutover Backup:** `/opt/personal-plan/staging/backups/20261101T211721Z-bfe4d035/backup-set.json`
* **Post-Cutover Backup:** `/opt/personal-plan/staging/backups/20261101T212710Z-e586ccd5/backup-set.json`
* **Table Seal Audit:** All 170 financial table seals matched 100% across the cutover (`status: "PASS"`).

---

## 4. Live Runtime Health & Verification Facts

Verified via `deploy/staging_v495.py verify`:
* `backend-1`: Healthy (`127.0.0.1:18000`)
* `frontend-1`: Healthy (`127.0.0.1:13000`)
* `worker-1`: Healthy (Scan & Monitor active)
* `research-worker-1`: Running
* `postgres-1`: Healthy
* `redis-1`: Healthy
* `curl http://127.0.0.1:18000/healthz` -> `{"status":"ok","mode":"paper","version":"4.9.5-rc.1"}`
* `curl http://127.0.0.1:18000/readyz` -> `{"ready":true,"live_trading_enabled":false}`
* `curl -I http://127.0.0.1:13000/` -> `HTTP/1.1 200 OK`

---

## 5. Rollback Procedure (Emergency Only)

If any unforeseen condition arises, the exact prior verified release (V4.9.4) remains present in the local staging repository and can be restored using the immutable images and database backup:
1. Stop running containers:
   ```bash
   cd /opt/personal-plan/staging && python3 releases/a71db8bcea94d018a77d60ed7d6937369a6105c4/deploy/staging_v494.py activate --commit a71db8bcea94d018a77d60ed7d6937369a6105c4 --images incoming/a71db8bcea94d018a77d60ed7d6937369a6105c4/release-binding.json
   ```
2. Verify financial seals across rollback.
