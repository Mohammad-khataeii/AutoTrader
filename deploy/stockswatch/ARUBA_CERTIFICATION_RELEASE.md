# StocksWatch certification and crypto challenger release

The 12 November 2026 audit captured 44 of 102 latest-session stock checks. A read-only Aruba follow-up found 50 certified observations for the 11 November session and fetched the required daily, closing-activity and corporate-action evidence for all 52 pending symbols. That provider check was read-only and did not update the production ledger.

The stock scanner now processes up to 12 assets per Alpaca Paper catch-up pass and waits two minutes between passes while refreshable work remains. SPY and held positions retain priority. Readiness checks the stored observation and certification together, and lists each unresolved symbol. Evidence still requires the same completed-session publication boundary, raw IEX bars, recent closing activity and corporate-action checks. The execution audit lists technical, timing, capital and protection vetoes independently. The overnight indicative route records optional data and actual fetch failures separately.

An OCO stop proven in the current broker order book retains its verified status when the optional ratchet quote is unavailable. Pending or uncertain broker modifications suppress stop proof until the next reconciliation. Historical replay and model computation run off the API event loop so they can yield to health requests.

Use `python -m stockswatch.session_audit YYYY-MM-DD --offset 0 --limit 25` in the StocksWatch image to retrieve persisted stock decisions. For a copied ledger set `STOCKSWATCH_DB` to its absolute path. The read-only audit and replay connections use WAL-aware reads and memory-backed SQLite temporary sorts. Historical rows retain their original reason codes.

## Crypto research

Run `python -m stockswatch.crypto_challenger_replay --db /path/to/stockswatch.sqlite3` against a stable read-only snapshot. All four candidates use the same 33 USD pairs and point-in-time completed bars. The relative-strength hypothesis requires at least a 1% 24-hour gain and at least two percentage points of outperformance against aligned BTC/USD observations, stable BTC, healthy RSI and volatility, and a rising close above the 20-hour EMA. Simulation uses next-hour midpoint opens, positive-volume fill paths, fees and slippage, gap-aware stop priority, and a 36-hour maximum. The trailing seven days are descriptive historical evidence. Per-strategy positions run independently across symbols and the drawdown is a proxy.

The Aruba sample covered 24,712 pair-hours. Modeled outcomes after fees and slippage were:

| Setup | All trades | All expectancy in R | Trailing 7-day trades | Trailing 7-day expectancy in R |
| --- | ---: | ---: | ---: | ---: |
| Breakout | 2 | +0.2860 | 0 | — |
| Continuation | 5 | -1.1431 | 0 | — |
| Recovery | 37 | -0.7544 | 8 | -0.9708 |
| Relative strength | 28 | -0.4757 | 5 | -0.9371 |

The sample supplies no basis for promotion. The comparison is research-only and the paper strategy switches stay under their existing controls.

## Aruba operator workflow

Use the reviewed commit and its release bundle from the development machine. The laptop needs Bash, Python 3.11 or newer and a working `aruba-vps` SSH alias. Run the read-only preflight first.

```bash
bash deploy/stockswatch/deploy_aruba.sh --preflight
```

The follow-up observed four paper stock positions and two open OCO orders, with zero crypto positions or unresolved intents. ACN and AMGN lacked a persisted broker OCO record at that check. Allow the existing paper lifecycle to reconcile the broker inventory before proceeding.

After release approval and a passing preflight, supply the full reviewed SHA and bundle path.

```bash
bash deploy/stockswatch/deploy_aruba.sh --deploy FULL_REVIEWED_SHA /absolute/path/to/release-bundle
```

The script verifies the uploaded source and Linux AMD64 image, retains the original image, takes an online SQLite backup and opens an isolated restore, then rechecks both Alpaca Paper books. It stops only the existing StocksWatch writer, makes and reconciles the cutover backup, and replaces only that service in `autotrader-aruba-stockswatch`. It verifies the running module hashes, ledger mount, inherited paper configuration, frontend health and broker connectivity. It keeps the original data mount and rollback inputs. The script leaves recovery evidence in the release state directory and does not restore over the active ledger.

Use the authenticated readiness route after startup to confirm the expected completed session and 102 certified assets. Then inspect the next core opening and crypto cycles for the persisted decision or broker submission result. Paper entries require the corresponding strategy and risk gates to pass.
