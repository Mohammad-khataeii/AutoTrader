"""Short PostgreSQL transactions coordinate acquisition, cooldown and observability."""

import json
from datetime import datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from sqlalchemy import select

from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import SystemStateModel


class MarketStateMixin:
    if TYPE_CHECKING:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from autotrader.persistence.models import AccountModel
        session_factory: async_sessionmaker[AsyncSession]

        async def _lock_account(self, session: Any) -> AccountModel: ...

    async def reserve_market_cache(
        self, key: str, bucket: int
    ) -> tuple[str | None, dict[str, Any]]:
        storage = "market_cache:" + sha256(key.encode()).hexdigest()[:32]
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = cast(SystemStateModel, await session.get(SystemStateModel, storage))
            value = json.loads(row.payload_json) if row else {}
            if value.get("bucket", -1) >= bucket:
                return None, value
            if (
                value.get("lease_until")
                and aware(datetime.fromisoformat(value["lease_until"])) > utc_now()
            ):
                return None, value
            token = uuid4().hex
            value.update(
                token=token,
                lease_until=(utc_now() + timedelta(seconds=45)).isoformat(),
                cache_key=key,
            )
            if row:
                row.payload_json = json.dumps(value)
            else:
                session.add(
                    SystemStateModel(
                        key=storage,
                        state="CACHE",
                        reason="shared_completed_candles",
                        payload_json=json.dumps(value),
                    )
                )
            return token, value

    async def publish_market_cache(
        self, key: str, token: str, bucket: int, candles: list[dict[str, Any]]
    ) -> None:
        storage = "market_cache:" + sha256(key.encode()).hexdigest()[:32]
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = cast(SystemStateModel, await session.get(SystemStateModel, storage))
            value = json.loads(row.payload_json)
            if value.get("token") != token:
                raise ValueError("market_cache_lease_lost")
            value.update(
                bucket=bucket, candles=candles, lease_until=None, refreshed_at=utc_now().isoformat()
            )
            row.payload_json = json.dumps(value)

    async def defer_public_requests(self, family: str, seconds: float) -> None:
        key = "public_rate:" + sha256(family.encode()).hexdigest()[:24]
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(SystemStateModel, key)
            payload = json.loads(row.payload_json) if row else {}
            deadline = utc_now() + timedelta(seconds=seconds)
            if payload.get("next_at"):
                deadline = max(deadline, aware(datetime.fromisoformat(payload["next_at"])))
            payload["next_at"] = deadline.isoformat()
            if row:
                row.payload_json = json.dumps(payload)
            else:
                session.add(
                    SystemStateModel(
                        key=key,
                        state="RATE_LIMIT",
                        reason="provider_cooldown",
                        payload_json=json.dumps(payload),
                    )
                )

    async def market_metric(self, event: str, value: float = 1) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(SystemStateModel, "market_metrics")
            payload = json.loads(row.payload_json) if row else {}
            payload[event] = payload.get(event, 0) + value
            payload["observed_at"] = utc_now().isoformat()
            # A separate identifiable measurement window; old cumulative
            # counters are never relabeled as measurements since deployment.
            now = utc_now()
            bucket = int(now.timestamp()) // 900
            window_key = "market_window:" + str(bucket)
            window_row = await session.get(SystemStateModel, window_key)
            window: dict[str, Any] = json.loads(window_row.payload_json) if window_row else {"started_at": now.isoformat(), "bucket_seconds": 900}
            window[event] = window.get(event, 0) + value
            window["observed_until"] = now.isoformat()
            if window_row:
                window_row.payload_json = json.dumps(window)
            else:
                session.add(SystemStateModel(key=window_key,state="MEASURED",reason="bounded_public_data_measurement_window",payload_json=json.dumps(window)))
            if event == "request_success":
                payload["last_successful_refresh"] = utc_now().isoformat()
            if row:
                row.payload_json = json.dumps(payload)
            else:
                session.add(
                    SystemStateModel(
                        key="market_metrics",
                        state="OBSERVING",
                        reason="real_acquisition_metrics",
                        payload_json=json.dumps(payload),
                    )
                )

    async def market_data_health(self) -> dict[str, Any]:
        async with self.session_factory() as session:
            metrics = await session.get(SystemStateModel, "market_metrics")
            caches = (
                await session.scalars(
                    select(SystemStateModel).where(SystemStateModel.key.like("market_cache:%"))
                )
            ).all()
            payload = json.loads(metrics.payload_json) if metrics else {}
            windows = (await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like("market_window:%")).order_by(SystemStateModel.created_at.desc()).limit(4))).all()
            cache_health = []
            for cache in caches:
                data = json.loads(cache.payload_json)
                cache_health.append(
                    {
                        "key": data.get("cache_key"),
                        "bucket": data.get("bucket"),
                        "observations": len(data.get("candles", [])),
                        "refreshed_at": data.get("refreshed_at"),
                        "age_seconds": (
                            utc_now() - aware(datetime.fromisoformat(data["refreshed_at"]))
                        ).total_seconds()
                        if data.get("refreshed_at")
                        else None,
                    }
                )
            requests = (
                payload.get("request_success", 0)
                + payload.get("request_429", 0)
                + payload.get("request_failure", 0)
            )
            return {
                **payload,
                "requests": requests,
                "mean_request_latency_ms": payload.get("request_latency_ms", 0) / requests
                if requests
                else None,
                "caches": cache_health,
                "measurement_windows": [json.loads(row.payload_json) for row in windows],
                "policy": "public REST, one request/second/family; provider Retry-After milliseconds; completed-candle incremental cache; protective book priority",
            }
