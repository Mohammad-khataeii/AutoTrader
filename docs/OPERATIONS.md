# Operations

## Start

```bash
cp .env.example .env
docker compose up --build
```

Dashboard: http://localhost:3000

API: http://localhost:8000

Default dashboard credentials are `admin` / `change-me`. Change them before deploying anywhere reachable.

## Stop

```bash
docker compose down
```

## Tests

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
cd frontend && npm install && npm test
```

## Migrations

```bash
alembic upgrade head
```

## Backtest

```bash
autotrader-backtest
```

The bundled CLI runs a deterministic sample backtest. Real historical backtests require loading candles from Revolut X documented OHLCV endpoints or another lawful historical data source.

## Logs

```bash
docker compose logs -f backend worker
```

## Backup

```bash
docker compose exec postgres pg_dump -U autotrader autotrader > autotrader.sql
```

## Restore

```bash
cat autotrader.sql | docker compose exec -T postgres psql -U autotrader autotrader
```

## OpenAI Configuration

OpenAI is disabled by default. To enable it later:

```env
AI_PROVIDER=openai
AI_MODEL=<actual-model-id>
OPENAI_API_KEY=<secret>
AI_MONTHLY_BUDGET_USD=10
```

The code does not assume an OpenAI Sol API identifier. Configure the actual model ID once available in your API account.

