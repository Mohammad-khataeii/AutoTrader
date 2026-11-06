# StocksWatch Alpaca Paper deployment

This is an operator-run staging cutover. Run the commands on the staging server as a trusted operator with local Docker access, except for the source packaging step. The helper accepts the existing staging project `autotrader-aruba-test`, the staged SQLite bind under `/opt/personal-plan/staging` and the existing frontend loopback port `127.0.0.1:13000`. Confirm these from preflight. The historical installers targeted this topology. A different topology requires review and a source change before use.

The scoped project `autotrader-aruba-stockswatch` has exactly two services. It attaches to the existing staging networks as external networks and keeps service aliases, the SQLite mount, the frontend loopback port, the frontend proxy routes and backend session validation. The original StocksWatch and frontend containers are retained, stopped during cutover, and available for inspection. Use the scoped helper for all subsequent operations on these services. Coordinate any broader staging Compose operation first because the original full stack still describes its own frontend and StocksWatch.

## A. Prepare the immutable source and prerequisites

On the development machine, set `RELEASE_SHA` to the reviewed **full commit SHA** from the release delivery. The release archive and its SHA256 are generated from committed files.

```sh
git fetch origin feature/stockswatch-alpaca-paper-integration
git show --no-patch "$RELEASE_SHA"
python3 deploy/release.py prepare --ref "$RELEASE_SHA" --output "$HOME/stockswatch-releases"
```

Use Python 3.11 or later on the server, Linux AMD64 Docker Engine and Docker Compose 2.30 or later for raw env files. Docker must use the local Unix socket, with `DOCKER_HOST` and `DOCKER_CONTEXT` unset. The build requires registry and package download access, sufficient free disk space on Docker's storage filesystem, and the existing StocksWatch image as a verified local base. The runtime requires outbound HTTPS to Alpaca and the configured research providers. Check Docker's data filesystem as well as the state and ledger filesystems.

Transfer the archive and its printed SHA256 through your approved channel. In a server shell set these values to the actual approved values and local archive path. Create a fresh private state directory on a filesystem with enough capacity.

```sh
umask 077
RELEASE_SHA='<approved full 40-character SHA>'
ARCHIVE='<absolute path to the transferred release tar.gz>'
ARCHIVE_SHA256='<SHA256 from the reviewed release delivery>'
printf '%s  %s\n' "$ARCHIVE_SHA256" "$ARCHIVE" | sha256sum --check --strict -
STATE="/opt/personal-plan/staging/integrations/stockswatch-alpaca-${RELEASE_SHA}"
mkdir -m 700 "$STATE"
mkdir -m 700 "$STATE/source"
tar --no-same-owner --no-same-permissions -xzf "$ARCHIVE" -C "$STATE/source"
cd "$STATE/source"
python3 deploy/release.py verify --manifest release-manifest.json --commit "$RELEASE_SHA"
TOOL="$PWD/deploy/stockswatch/scoped_release.py"
```

Keep credentials on the server. The two paper keys come from the Alpaca **Paper Trading** dashboard. The two data keys must authorize historical IEX stock data and corporate actions. They may be the same pair if your Alpaca entitlement permits both uses. Set the expected full account number or UUID from a trusted source. Account verification matches the full value, while the UI shows a suffix. Historical balances and identifiers are examples of previous observations. Use the current Alpaca dashboard for comparison.

```sh
install -m 600 deploy/stockswatch/runtime.env.example "$STATE/operator.env"
${EDITOR:-vi} "$STATE/operator.env"
```

Use raw, unquoted `KEY=value` lines without inline comments, shell expansions or trailing spaces. The helper inherits allowlisted optional scanner/Gemini settings from the running StocksWatch unless you provide an explicit replacement. Existing Redis/Gemini dependencies are used for supplementary research only. Review those settings privately if applicable. Keep both the operator file and generated runtime file private. Avoid shell tracing, printing `docker inspect` environment data, or rendering Compose configuration with secrets. `POSTGRES_PASSWORD`, `DASHBOARD_PASSWORD`, `PAPER_MULTI_PERPETUALS_ENABLED`, `GRAFANA_ADMIN_PASSWORD` and `STAGING_DATABASE_URL` have no role in this Compose model.

## B. Run read-only server preflight

```sh
python3 "$TOOL" preflight
docker compose version
docker info --format '{{.OSType}}/{{.Architecture}} {{.DockerRootDir}}'
df -h "$STATE" /opt/personal-plan/staging "$(docker info --format '{{.DockerRootDir}}')"
docker ps --filter label=com.docker.compose.project=autotrader-aruba-test \
  --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
curl --fail --silent --show-error http://127.0.0.1:13000/healthz
```

Preflight identifies one running original StocksWatch, frontend and core backend by Compose labels, checks SQLite integrity and reconciles local cash, shares and fill/order relationships, checks network aliases, and probes core health from the existing StocksWatch container. Confirm the reported mount and image configuration IDs, loopback port, and core health. Review both original target configurations for nonstandard settings before proceeding. Confirm the staging HTTPS URL and authenticate in the browser using the existing AutoTrader session. The helper does not change the reverse proxy or TLS.

## C. Verify backups and build the candidate images

```sh
python3 "$TOOL" prepare --state "$STATE" --commit "$RELEASE_SHA" \
  --runtime-env "$STATE/operator.env"
python3 -m json.tool "$STATE/plan.json"
```

Prepare verifies the source, records the original container and image IDs and selected non-secret settings, takes a SQLite online backup from a read transaction, opens the backup separately and verifies its financial fingerprint and SQLite integrity. It builds the two Linux AMD64 images from manifest-verified files, checks their revision labels, pins their configuration IDs, and validates the two-service Compose files without printing their environment. This step leaves the running containers in place. Expect `before.sqlite3`, `plan.json`, and the private Compose inputs. Compare the plan to the reviewed staging inventory. Retain the state directory, both original containers and the associated image layers. Keep the database backup according to your private backup policy. The private state directory holds one build log per image.

## D. Cut over in read-only mode

```sh
python3 "$TOOL" apply --state "$STATE" --commit "$RELEASE_SHA"
curl --fail --silent --show-error http://127.0.0.1:13000/healthz
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:13000/api/stockswatch/status
```

The helper stops the original StocksWatch writer, verifies a second isolated snapshot `cutover.sqlite3`, stops the original frontend, and starts only the two pinned candidates. Expect healthy containers and HTTP 401 on the unauthenticated StocksWatch route. It checks the new backend's paper mode, loopback frontend, network discovery, session gate, legacy financial fingerprint and untouched staging peers. A failure after cutover begins triggers a scoped fallback to the retained frontend with StocksWatch stopped. Preserve the plan, backups and Docker logs for diagnosis.

## E. Verify the Alpaca account in read-only mode

1. Open StocksWatch on the existing staging dashboard and wait for broker synchronization. Confirm **CONNECTED**, the masked paper account, **Read-only**, and a recent successful sync. Use the authenticated dashboard or the browser Network panel for `GET /api/stockswatch/status` and `GET /api/stockswatch/dashboard`. Keep response data private.
2. Compare equity, cash, buying power, positions, orders and fills against Alpaca Paper. Allow for refresh timing differences. Review any separate warning for history, orders or fills. A missing component is explicitly unavailable. Portfolio history uses a one-month broker view. Realized P&L remains unavailable because this view does not reconstruct tax lots, transfers and corporate actions.
3. Open Portfolio → Automation and audit. Confirm the legacy records are separated from broker orders. If AAPL, MA, V, ABBV and COST were pending at cutover, they should still be pending in the legacy audit. Verify the scanner advances through completed-session prices with the Alpaca provider. Read-only verification needs no order placement.

## F. Arm paper submission as a separate operation

Confirm the correct account, current broker and scanner health, complete certified IEX coverage, acceptable risk settings and no unresolved intent. Reconcile existing external orders in Alpaca. Use **Pause new paper orders** if the dashboard is armed and verify the persisted pause is on. Then run:

```sh
python3 "$TOOL" arm --state "$STATE" --commit "$RELEASE_SHA"
```

Only StocksWatch is recreated. The helper requires a linked account, a persisted pause and no outstanding managed intent. Confirm the dashboard still shows **Paused** after restart. Use **Resume paper orders** in the authenticated dashboard when you want to admit autonomous paper orders. Pause stops future BUY and SELL admission, including software exits. Orders already accepted at Alpaca retain their broker lifecycle.

The strategy uses the latest published completed session (publication boundary 00:15 New York time), exchange calendar and a fresh Alpaca clock. It submits during the first hour of the next regular session only. Entries require a fresh full-universe scan attempt, certified symbol and SPY observations, the existing regime/score, under 70% annualized 20-session volatility, and at least $1 million of 20-session average daily IEX dollar volume. A one-venue daily bar and recent corporate-action check are partial market evidence. Stale or unavailable checks block admission.

BUY orders are whole-share DAY limits capped at 0.5% above the certified close, rounded down to cents. The limits are 12% of equity per symbol, 26% per sector, 60% total gross exposure, a 40% equity cash buffer, five simultaneous position slots and two BUY attempts per signal day. Remaining open BUY quantities reserve at their own limit price. Entries also require non-marginable buying power and block at a 3.5% daily equity loss or 12% one-month drawdown. The displayed leveraged buying power does not fund the strategy. Reserve the paper account for this worker while armed. Simultaneous manual changes can race the broker's separate endpoints even though the worker rechecks the account before each order.

SELLs are software-driven DAY market exits for verified strategy-owned long shares. Triggers use a certified close at or below 92% of broker average entry, below 96% of the 50-session mean, or a score below 0.8. Existing manual positions are visible and count toward entry risk. Manual activity in a strategy position, insufficient fill coverage, ambiguous corporate actions, or an overlapping order blocks unattended liquidation. The strategy places no broker-held protective or take-profit orders. Gaps, outages, closures, pause, and missing data can defer or worsen the exit. A strategy-owned symbol may become ineligible for automatic exits when its entry falls outside the complete recent fill window.

## G. Monitor and disarm

```sh
docker ps --filter label=com.docker.compose.project=autotrader-aruba-stockswatch \
  --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
SW="$(docker ps -q --filter label=com.docker.compose.project=autotrader-aruba-stockswatch \
  --filter label=com.docker.compose.service=stockswatch)"
test -n "$SW"
docker logs --tail 200 "$SW"
```

Check last successful synchronization, certified price freshness, the decision funnel, broker status and intent records after market open. Compare orders and fills by broker order ID and client ID. `BROKER_ACKNOWLEDGED` reflects an order response. Actual execution comes from Alpaca fill activity and may occur in parts. In a degraded connection, the dashboard retains sync metadata and hides stale broker financial fields. The broker engine and the scanner run separately on the server.

Pause from the dashboard first if available, then disarm:

```sh
python3 "$TOOL" disarm --state "$STATE" --commit "$RELEASE_SHA"
```

Confirm read-only and review any accepted orders in Alpaca. If health or an unrelated staging change prevents the helper from running, independently compare the scoped StocksWatch container's full ID, project/service labels and image configuration ID with the reviewed plan before using `docker stop --time 180 <verified-full-scoped-stockswatch-container-id>`. Review orders at Alpaca immediately after an emergency stop.

## H. Roll back

1. Pause/disarm when available. In Alpaca Paper review all open, partial and recently filled orders, including managed client IDs. Decide how to handle any open orders from Alpaca using your normal operator process. Recheck terminal outcomes, fills and current positions.
2. Restore the original frontend with the scoped helper.

   ```sh
   python3 "$TOOL" rollback --state "$STATE" --commit "$RELEASE_SHA"
   curl --fail --silent --show-error http://127.0.0.1:13000/healthz
   ```

3. The helper stops scoped containers and starts the retained original frontend by ID. StocksWatch stays stopped because the original local simulator could settle or change historical pending orders if restarted. Preserve the current SQLite ledger, cutover backups, original containers, candidate containers and image IDs. Use a separately reviewed read-only StocksWatch release to restore the StocksWatch route. An SQLite restore cannot reverse broker orders or fills. Investigate a database incident against an isolated copy before considering any restoration.

## I. Troubleshoot by failure mode

| Symptom | Check and response |
| --- | --- |
| Compose asks for passwords, Grafana, perpetuals or staging database values | Confirm you are using the helper and its scoped JSON files. Use `config --quiet` only, with the explicit state directory and empty interpolation env file. Shared-stack interpolation happens even when you name two services. |
| Container or network preflight fails | Review `docker ps` by project and service label and compare IDs, network aliases and mount in the plan. A stopped original plus a running scoped service is normal after cutover. If the core or network was replaced, stop and review the new topology. |
| Missing configuration or account mismatch | Confirm the raw operator env file, exact expected paper account identity and current credentials in Alpaca Paper. Before cutover, prepare fresh state. After cutover, use the correction procedure below. An existing linked ledger rejects a different account. |
| Market authorization, data or timing gate | Inspect scanner stage, source errors and completed-session dates. Check IEX historical and corporate-action entitlements, NYSE holidays/early closes, Alpaca clock and server time synchronization. Allow the full universe scan to complete before the opening window ends. |
| Five pending legacy orders appear | Review them under legacy audit. The StocksWatch broker worker does not process that ledger. |
| Broker rejects an order | Review the broker order status and local diagnostic. A definite insufficient-buying-power rejection is recorded, and any ambiguous POST error follows the uncertain-order path. |
| An uncertain intent remains | Keep read-only and paused. Inspect the client ID in Alpaca Paper and ask Alpaca to confirm any uncertain submission. The worker queries the original ID on every sync. A lookup returning 404 alone does not clear the intent. See the recovery procedure below. |
| DB or startup failure | Review bind source, permissions for the inherited image user, available disk, and worker lock. Run SQLite checks against the backup copy. A second worker on the live ledger is unsafe. |
| Build, apply or restart fails | Preserve the full release SHA, protected state and candidate/original IDs. Review local container health and protected logs. If needed rebuild from an independently reviewed source release. Keep old containers and both backup files. |

For a credential correction after cutover, reconcile accepted orders in Alpaca Paper and roll back the frontend using section H. Then edit the private operator file, update the approved plan and reapply the same images in read-only mode.

```sh
${EDITOR:-vi} "$STATE/operator.env"
python3 "$TOOL" configure --state "$STATE" --commit "$RELEASE_SHA" --runtime-env "$STATE/operator.env"
python3 "$TOOL" apply --state "$STATE" --commit "$RELEASE_SHA"
```

This keeps the existing account linkage and broker intent history. The private state directory retains the previous runtime configuration. If a host crash interrupts configuration and produces a checksum mismatch, compare the previous file hash to the reviewed plan and restore that file before retrying.

For an uncertain `PREPARED` or `UNKNOWN` intent, record absence only after Alpaca has explicitly confirmed that no order was created, the original execution session has ended, and the worker is read-only and paused. Set `CLIENT_ID` and `ALPACA_CASE` from the dashboard and support case. Then run:

```sh
docker exec "$SW" /opt/stockswatch/venv/bin/python -m stockswatch.alpaca_paper \
  "$CLIENT_ID" --support-case "$ALPACA_CASE" --alpaca-confirmed-absence
```

This rechecks the linked paper account and original client ID and records the resolution. The client ID remains reserved. A missing previously acknowledged order or ambiguous position ownership requires broker reconciliation and review before arming.

## Research evidence

Run `python3 -m stockswatch.challengers <directory-of-symbol.research.json-files>` with the historical inputs whose SHA256s are listed in `stockswatch/research_evidence.json`. Each file is a JSON array of `[day, open, high, low, close, volume]` rows. The repo stores the reproducible runner, hashes and outputs. The provider input files are separate. The revised simulation uses prior-day signals and next-session opening proxies, tests 12/30/60 basis points per side, and reports return, drawdown, Sharpe, profit factor, expectancy, closed win/loss counts, turnover, exposure and results by prior regime.

The baseline proxy returned 7.68% in the earlier segment and 9.81% in the November 2025 to November 2026 holdout at 12 basis points per side. The alternative risk exit returned 6.82% and 11.52%, respectively. At 60 basis points in the holdout it returned 7.44% versus 7.65% for the baseline. The ensemble's holdout fell from 10.70% to 4.23% as costs increased. The ranking is sensitive to cost assumptions and the period tested. Runtime retains the existing deterministic strategy rules with added execution and risk verification. The small current-ticker IEX panel has survivorship bias and incomplete corporate-action/total-return coverage. Simulated opening fills do not validate actual Alpaca execution or prospective performance.

## Alpaca references

- [Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading)
- [Orders and order lifecycle](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
- [Client order lookup](https://docs.alpaca.markets/us/reference/getorderbyclientorderid)
- [Account fill activities](https://docs.alpaca.markets/us/docs/account-activities)
- [Market data corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1)
