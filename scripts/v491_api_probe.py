"""Probe a network-isolated restored clone; never run against a live account."""
import argparse
import asyncio
import json
import os
import resource
import time
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url

from autotrader.api.main import app
from autotrader.config import get_settings
from autotrader.research.artifacts import source_fingerprint


async def probe(output: Path, concurrency: int) -> None:
    settings = get_settings()
    assert os.environ.get('ISOLATED_API_PROBE') == '1'
    assert settings.environment == 'staging' and not settings.live_trading_enabled
    assert make_url(settings.database_url).host == 'restore-postgres'
    result = {'scope': 'LOCAL_ISOLATED_RESTORED_CLONE_NO_EXTERNAL_NETWORK',
              'source_fingerprint': source_fingerprint()[0], 'concurrent_history_requests': concurrency}
    def save() -> None:
        output.write_text(json.dumps(result, indent=2)+'\n')
    async with app.router.lifespan_context(app):
        auth = httpx.BasicAuth(settings.dashboard_username, settings.dashboard_password.get_secret_value())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://isolated-probe', auth=auth) as client:
            before = (await client.get('/api/personal-paper')).json()
            assert before['portfolio']['control'] == 'PAUSED' and before['reconciliation'] == []
            assert before['portfolio']['positions'] == before['portfolio']['pending_orders'] == '0'
            result.update(current_path='/api/intelligence', initial_cash=before['portfolio']['cash'],
                          initial_fills=before['performance']['fills'])
            save()
            stopped = asyncio.Event()
            health_times = []
            delays = []
            async def health() -> None:
                expected = time.monotonic()
                while not stopped.is_set():
                    now = time.monotonic();delays.append(max(0, now-expected))
                    response = await client.get('/readyz')
                    assert response.status_code == 200
                    health_times.append(time.monotonic()-now)
                    expected = time.monotonic()+.1
                    await asyncio.sleep(.1)
            task = asyncio.create_task(health())
            async def request() -> dict:
                start = time.monotonic();response = await client.get('/api/intelligence')
                seconds = time.monotonic()-start
                assert response.status_code == 200
                body = response.json()
                return {'seconds': seconds, 'bytes': len(response.content), 'episodes': len(body['episodes']),
                        'episode_scope': body['episode_scope'], 'missed': len(body['missed']), 'rows': len(body['rows'])}
            try:
                observations = await asyncio.gather(*(request() for _ in range(concurrency)))
            finally:
                stopped.set();await task
            after = (await client.get('/api/personal-paper')).json()
            assert after['reconciliation'] == [] and after['portfolio']['control'] == 'PAUSED'
            assert after['portfolio']['cash'] == before['portfolio']['cash']
            assert after['performance']['fills'] == before['performance']['fills']
            result.update(status='PASS', observations=observations,
                          max_health_request_seconds=max(health_times, default=0),
                          max_event_loop_delay_seconds=max(delays, default=0),
                          max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                          financial_state_unchanged=True, real_time_market_claim=False)
            save();print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--concurrency', type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    asyncio.run(probe(args.output, args.concurrency))
