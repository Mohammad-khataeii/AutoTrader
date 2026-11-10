"""Apply the reviewed closed-market explanation to the exact live broker file.

This is a source-preserving one-hunk transplant, NOT a broker engine replacement
or new execution policy. The deployment pins and verifies the original Git blob.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path

OLD = '''    if not signals or day != completed_day(now):
        return {**result, "status": "NO_CERTIFIED_CURRENT_SIGNALS"}
    if not _open_window(client, day, now):
        return {**result, "status": "WAITING_FOR_NEXT_CORE_OPEN_WINDOW"}'''
NEW = '''    if not signals or day != completed_day(now):
        return {**result, "status": "NO_CERTIFIED_CURRENT_SIGNALS"}
    if not _open_window(client, day, now):
        # Only verified technical reasons are known when the broker entry
        # window is shut; don't claim other broker gates were evaluated.
        def closing_reason(signal):
            if signal["score"] < SCORE_MIN or signal["regime"] != "RISK_ON":
                return "technical_score_or_regime_below_gate"
            if signal["features"]["volatility_annual"] >= MAX_VOLATILITY:
                return "technical_volatility_cap"
            if signal["iex_dollar_volume_20d"] < MIN_IEX_DOLLAR_VOLUME:
                return "technical_iex_liquidity_cap"
            return "entry_window_closed_remaining_broker_gates_not_evaluated"
        result["why_no_trade"] = [
            {"symbol": signal["symbol"], "action": "WATCH",
             "reason": closing_reason(signal)} for signal in signals
        ]
        return {**result, "status": "WAITING_FOR_NEXT_CORE_OPEN_WINDOW"}'''


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def patch_source(text: str) -> str:
    if text.count('def _preview_and_submit(') != 1:
        raise ValueError('unexpected_broker_function_layout')
    if text.count(OLD) != 1:
        raise ValueError('expected_closed_window_hunk_missing_or_modified')
    try:
        parsed = ast.parse(text)
    except SyntaxError as exc:
        raise ValueError('invalid_original_broker_python') from exc
    funcs = [n for n in parsed.body if isinstance(n, ast.FunctionDef)
             and n.name == '_preview_and_submit']
    if len(funcs) != 1:
        raise ValueError('preview_function_not_unique')
    first_line = text.count('\n', 0, text.index(OLD)) + 1
    if not funcs[0].lineno < first_line <= funcs[0].end_lineno:
        raise ValueError('closed_window_hunk_outside_expected_function')
    changed = text.replace(OLD, NEW, 1)
    ast.parse(changed)
    if changed.replace(NEW, OLD, 1) != text:
        raise ValueError('unexpected_broker_source_change')
    return changed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('--expected-sha', required=True)
    a = p.parse_args()
    data = Path(a.input).read_bytes()
    sha = git_blob_sha(data)
    if sha != a.expected_sha:
        raise SystemExit(f'ABORT: broker source changed ({sha}); no files changed')
    text = data.decode('utf-8')
    changed = patch_source(text).encode('utf-8')
    if changed == data:
        raise SystemExit('ABORT: patch did not change broker source')
    out = Path(a.output)
    if out.resolve() == Path(a.input).resolve():
        raise SystemExit('ABORT: input and output cannot be the same file')
    out.write_bytes(changed)
    print(f'BROKER_HUNK_OK: original={sha} updated={git_blob_sha(changed)}; no other code changed')


if __name__ == '__main__':
    main()
