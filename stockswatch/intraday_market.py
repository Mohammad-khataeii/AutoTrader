"""Bounded authenticated Alpaca stock observations, independent of EOD calculations."""

import itertools
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from .market import alpaca_headers
from .sessions import instant, session

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
    def __init__(self, transport=None, sleeper=time.sleep):
        self.client = httpx.Client(
            base_url=DATA_ORIGIN,
            timeout=httpx.Timeout(4, connect=2),
            headers=alpaca_headers(),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )
        self.sleep = sleeper
        self.closes = {}

    def close(self):
        self.client.close()

    def get(self, path, params):
        if path not in {"/v2/stocks/snapshots", "/v2/stocks/bars", "/v1/corporate-actions"}:
            raise ObservationError("unapproved_intraday_data_route")
        for attempt in range(2):
            try:
                response = self.client.get(path, params=params)
            except httpx.TransportError:
                if attempt:
                    raise ObservationError("intraday_data_transport_unavailable") from None
            else:
                status = response.status_code
                if status in (401, 403, 422):
                    raise ObservationError("intraday_feed_or_entitlement_denied")
                if status == 429:
                    # Let the next bounded cycle respect the quota instead of looping.
                    raise ObservationError("intraday_data_rate_limited")
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
                if status < 500 or attempt:
                    raise ObservationError(f"intraday_data_http_{status}")
            self.sleep(0.25)

    def snapshots(self, symbols, feed):
        if feed not in FEEDS or not 0 < len(symbols) <= 32:
            raise ObservationError("intraday_feed_or_universe_invalid")
        result = self.get("/v2/stocks/snapshots", {"symbols": ",".join(symbols), "feed": feed})
        if set(result) - set(symbols):
            raise ObservationError("intraday_snapshot_unexpected_symbol")
        return result

    def bars(self, symbols, feed, start, end):
        if feed not in FEEDS or not 0 < len(symbols) <= 32 or end - start > 30 * MINUTE:
            raise ObservationError("intraday_bar_request_outside_budget")
        params = {
            "symbols": ",".join(symbols),
            "feed": feed,
            "timeframe": "1Min",
            "adjustment": "raw",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 1000,
        }
        result = {s: [] for s in symbols}
        tokens = set()
        for _ in range(3):
            body = self.get("/v2/stocks/bars", params)
            data = body.get("bars")
            if not isinstance(data, dict) or set(data) - set(symbols):
                raise ObservationError("intraday_bar_response_invalid")
            for symbol, items in data.items():
                if not isinstance(items, list) or not all(isinstance(b, dict) for b in items):
                    raise ObservationError("intraday_bar_response_invalid")
                result[symbol].extend(items)
            token = body.get("next_page_token")
            if not token:
                return result
            if not isinstance(token, str) or token in tokens:
                break
            tokens.add(token)
            params["page_token"] = token
        raise ObservationError("intraday_bar_pagination_incomplete")

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
        result.append({"at": stamp, "close": close, "volume": volume, "turnover": volume * close})
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
