"""Bounded authenticated Alpaca stock observations, independent of EOD calculations."""

import itertools
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from .market import alpaca_headers
from .sessions import instant, session
from .universe import REGISTRY

BATCH = 32

DATA_ORIGIN = "https://data.alpaca.markets"
FEEDS = frozenset({"iex", "sip", "delayed_sip", "boats", "overnight"})
MINUTE = timedelta(minutes=1)


def _non_json_number(value):
    raise ValueError("non_finite_json_number")


class ObservationError(RuntimeError):
    pass


def positive(value):
    try:
        number = Decimal(str(value))
        if number.is_finite() and number > 0:
            return number
    except InvalidOperation:
        pass
    raise ObservationError("missing_or_invalid_positive_value")


class IntradayData:
    def __init__(self, transport=None, sleeper=time.sleep, *, background=False):
        self.client = httpx.Client(
            base_url=DATA_ORIGIN,
            timeout=httpx.Timeout(4, connect=2),
            headers=alpaca_headers(),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )
        self.sleep = sleeper
        self.background = background
        self.closes = {}

    def close(self):
        self.client.close()

    def get(self, path, params):
        if path not in {"/v2/stocks/snapshots", "/v2/stocks/bars", "/v1/corporate-actions"}:
            raise ObservationError("unapproved_intraday_data_route")
        if self.background:
            self.sleep(0.6)
        attempts = 3 if self.background else 2
        for attempt in range(attempts):
            try:
                response = self.client.get(path, params=params)
            except httpx.TransportError:
                if attempt + 1 == attempts:
                    raise ObservationError("intraday_data_transport_unavailable") from None
            else:
                status = response.status_code
                if status == 401:
                    raise ObservationError("intraday_data_authentication_failed")
                if status == 403:
                    raise ObservationError("intraday_feed_or_entitlement_denied")
                if status == 429:
                    try:
                        delay = float(response.headers.get("Retry-After", str(2**attempt)))
                        reset = float(response.headers.get("X-RateLimit-Reset", "0"))
                        delay = max(delay, reset - time.time())
                    except ValueError:
                        delay = 60
                    if not self.background or attempt + 1 == attempts or not 0 <= delay <= 10:
                        raise ObservationError("intraday_data_rate_limited")
                    self.sleep(delay)
                    continue
                if response.is_success:
                    try:
                        if len(response.content) > 2_000_000:
                            raise ValueError("intraday_payload_too_large")
                        value = response.json(parse_constant=_non_json_number)
                    except ValueError:
                        raise ObservationError("intraday_data_invalid_json") from None
                    if isinstance(value, dict):
                        return value
                    raise ObservationError("intraday_data_invalid_shape")
                if status < 500 or attempt + 1 == attempts:
                    raise ObservationError(f"intraday_data_http_{status}")
            self.sleep(0.25 * 2**attempt)

    def snapshots(self, symbols, feed):
        self._validate_symbols(symbols, feed)
        result = {}
        for offset in range(0, len(symbols), BATCH):
            batch = symbols[offset : offset + BATCH]
            body = self.get("/v2/stocks/snapshots", {"symbols": ",".join(batch), "feed": feed})
            if set(body) - set(batch):
                raise ObservationError("intraday_snapshot_unexpected_symbol")
            result.update(body)
        return result

    @staticmethod
    def _validate_symbols(symbols, feed):
        if (
            feed not in FEEDS
            or not symbols
            or len(set(symbols)) != len(symbols)
            or set(symbols) - REGISTRY.keys()
        ):
            raise ObservationError("intraday_feed_or_universe_invalid")

    def bar_page(self, symbols, feed, start, end, timeframe, adjustment, token=None):
        self._validate_symbols(symbols, feed)
        if len(symbols) > BATCH:
            raise ObservationError("intraday_bar_batch_too_large")
        params = {
            "symbols": ",".join(symbols),
            "feed": "boats" if feed == "overnight" else feed,
            "timeframe": timeframe,
            "adjustment": adjustment,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 1000,
        }
        if token:
            params["page_token"] = token
        body = self.get("/v2/stocks/bars", params)
        data = body.get("bars")
        next_token = body.get("next_page_token")
        if (
            not isinstance(data, dict)
            or set(data) - set(symbols)
            or any(
                not isinstance(items, list) or any(not isinstance(b, dict) for b in items)
                for items in data.values()
            )
            or (next_token is not None and not isinstance(next_token, str))
        ):
            raise ObservationError("intraday_bar_response_invalid")
        return data, next_token

    def bars(self, symbols, feed, start, end, *, max_window=30 * MINUTE):
        self._validate_symbols(symbols, feed)
        if not start < end or end - start > max_window:
            raise ObservationError("intraday_bar_request_outside_budget")
        result = {s: [] for s in symbols}
        for offset in range(0, len(symbols), BATCH):
            batch = symbols[offset : offset + BATCH]
            tokens = set()
            token = None
            for _ in range(16 if max_window > 30 * MINUTE else 3):
                page, token = self.bar_page(batch, feed, start, end, "1Min", "raw", token)
                for symbol, items in page.items():
                    result[symbol].extend(items)
                if not token:
                    break
                if token in tokens:
                    raise ObservationError("intraday_bar_pagination_incomplete")
                tokens.add(token)
            else:
                raise ObservationError("intraday_bar_pagination_incomplete")
        return result

    def regular_closes(self, symbols, feed, day):
        # BOATS cannot provide an NYSE regular close. Use explicit IEX
        # reference with independent provenance for overnight observation only.
        feed = feed if feed in {"sip", "iex", "delayed_sip"} else "iex"
        key = (tuple(symbols), feed, day)
        if key not in self.closes:
            _, end = session(day)
            start = end - 5 * MINUTE
            bars = self.bars(symbols, feed, start, end)
            result = {}
            for symbol, values in bars.items():
                try:
                    parsed = parse_bars(values, start, end)
                    if parsed and parsed[-1]["at"] >= end - 2 * MINUTE:
                        result[symbol] = {
                            "price": str(parsed[-1]["close"]),
                            "at": parsed[-1]["at"].isoformat(),
                            "feed": feed,
                            "day": day,
                        }
                except ObservationError:
                    continue
            if len(result) == len(symbols):
                self.closes = {key: result}
            return result
        return self.closes[key]

    def corporate_actions(self, symbol, start, end):
        body = self.get(
            "/v1/corporate-actions",
            {
                "symbols": symbol,
                "start": start,
                "end": end,
                "data_quality": "all",
                "region": "all",
                "limit": 1000,
            },
        )
        actions = body.get("corporate_actions")
        if not isinstance(actions, dict) or body.get("next_page_token"):
            raise ObservationError("intraday_corporate_actions_unverified")
        events = []
        for kind, records in actions.items():
            if not isinstance(records, list):
                raise ObservationError("intraday_corporate_actions_unverified")
            for record in records:
                if not isinstance(record, dict):
                    raise ObservationError("intraday_corporate_actions_unverified")
                stamp = record.get("ex_date") or record.get("effective_date")
                try:
                    day = datetime.strptime(stamp, "%Y-%m-%d").date().isoformat()
                except (ValueError, TypeError):
                    raise ObservationError("intraday_corporate_action_date_unknown") from None
                if start <= day <= end:
                    events.append({"kind": kind, "day": day})
        return events


def parse_bars(rows, start, end):
    result = []
    previous = None
    for bar in rows:
        try:
            stamp = instant(bar["t"])
            opening, high, low, close, volume = (
                positive(bar[k]) for k in ("o", "h", "l", "c", "v")
            )
            if stamp == end:  # Alpaca end is inclusive and the endpoint may include a forming bar.
                continue
            if (
                not start <= stamp
                or stamp + MINUTE > end
                or stamp.second
                or stamp.microsecond
                or (previous is not None and stamp <= previous)
                or not low <= min(opening, close) <= max(opening, close) <= high
            ):
                raise ObservationError("intraday_invalid_bar_sequence")
        except (KeyError, TypeError, ValueError):
            raise ObservationError("intraday_invalid_bar") from None
        result.append(
            {
                "at": stamp,
                "close": close,
                "volume": volume,
                "turnover": volume * close,
                "high": high,
                "low": low,
            }
        )
        previous = stamp
    return result


def observe(symbol, raw, bars, reference, phase, feed, observed_at):
    data = {
        "symbol": symbol,
        "session": phase.name,
        "feed": feed,
        "observed_at": observed_at.isoformat(),
        "previous_regular_close": reference,
        "valid": False,
        "action": "WAIT",
    }
    if not isinstance(raw, dict):
        return {**data, "reason": "intraday_snapshot_missing"}
    quote, trade = raw.get("latestQuote"), raw.get("latestTrade")
    if isinstance(quote, dict):
        data["quote"] = {k: quote.get(k) for k in ("t", "bp", "ap", "bs", "as", "bx", "ax", "c")}
    if isinstance(trade, dict):
        data["trade"] = {k: trade.get(k) for k in ("t", "p", "s", "x", "c")}
    if raw.get("halted") is True or raw.get("trading_halted") is True:
        return {**data, "reason": "intraday_halted"}
    try:
        if not quote or not trade:
            raise ObservationError("intraday_quote_or_trade_missing")
        qtime, ttime = instant(quote["t"]), instant(trade["t"])
        if (
            not phase.contains(qtime)
            or not phase.contains(ttime)
            or not timedelta(0) <= observed_at - qtime <= timedelta(seconds=12)
            or not timedelta(0) <= observed_at - ttime <= timedelta(seconds=40)
        ):
            raise ObservationError("intraday_stale_future_or_cross_session_tick")
        bid, ask, bs, ask_size, price, size = (
            positive(v)
            for v in (quote["bp"], quote["ap"], quote["bs"], quote["as"], trade["p"], trade["s"])
        )
        if bid >= ask:
            raise ObservationError("intraday_locked_or_crossed_quote")
        midpoint = (bid + ask) / 2
        spread = (ask - bid) / midpoint * 10000
        data["spread_bps"] = str(spread)
        if spread > 35 or min(bid * bs, ask * ask_size) < 750:
            raise ObservationError("intraday_insufficient_displayed_liquidity")
        if feed == "sip" and (
            quote.get("c") != ["R"] or not quote.get("bx") or not quote.get("ax")
        ):
            raise ObservationError("intraday_quote_not_regular_executable")
        if feed == "sip" and (
            not isinstance(trade.get("c"), list) or set(trade["c"]) - {"@", "I", "T", "F", " ", "E"}
        ):
            raise ObservationError("intraday_trade_condition_unverified")
        if not bid * Decimal(".995") <= price <= ask * Decimal("1.005") or size <= 0:
            raise ObservationError("intraday_trade_quote_disagreement")
        data["quote_ready"] = True
        if not reference:
            raise ObservationError("intraday_previous_regular_close_missing")
        end = observed_at.replace(second=0, microsecond=0)
        parsed = parse_bars(bars, max(phase.start, end - 20 * MINUTE), end)
        if len(parsed) < 6 or parsed[-1]["at"] != end - MINUTE:
            raise ObservationError("intraday_recent_completed_bars_missing")
        last = parsed[-6:]
        if any(b["at"] - a["at"] != MINUTE for a, b in itertools.pairwise(last)):
            raise ObservationError("intraday_recent_completed_bar_gap")
        gap = midpoint / positive(reference["price"]) - 1
        if abs(gap) > Decimal(".20"):
            raise ObservationError("intraday_price_discontinuity")
        move = last[-1]["close"] / last[0]["close"] - 1
        turnover = sum(b["turnover"] for b in last[-3:])
        data.update(
            valid=True,
            reason="intraday_observed",
            gap=str(gap),
            momentum=str(move),
            higher_closes=sum(b["close"] > a["close"] for a, b in itertools.pairwise(last)),
            minute_volume=str(last[-1]["volume"]),
            turnover_3m=str(turnover),
            latest_completed_at=(last[-1]["at"] + MINUTE).isoformat(),
            cost_bps=str(spread + Decimal(10)),
            bar_window=[
                {**{k: str(v) for k, v in b.items() if k != "at"}, "at": b["at"].isoformat()}
                for b in last
            ],
        )
    except (KeyError, TypeError, ValueError):
        data["reason"] = "intraday_invalid_observation"
    except ObservationError as exc:
        data["reason"] = str(exc)
    return data
