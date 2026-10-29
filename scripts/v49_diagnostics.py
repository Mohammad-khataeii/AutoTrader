"""Collect a bounded Aruba audit through ssh aruba-vps and summarize it locally."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def hourly(bundle: dict[str,Any]) -> str:
    primary=(bundle.get('registry',{}).get('primary') or {}).get('database_name')
    ledger=next((d for d in bundle['databases'] if d['database']==primary),{})
    groups: dict[str,list[dict[str,Any]]]=defaultdict(list)
    for row in ledger.get('signals',[]):groups[row['created_at'][:13]].append(row)
    lines=['# Hourly paper decision review','',f"Observed: {bundle['observed_at']} · window {bundle['hours']}h",'',
        'Original decisions, subsequent price paths, hypothetical execution and actual ledger fills are separate evidence. No strategy is promoted by this review.','']
    for hour,rows in sorted(groups.items()):
        symbols=sorted({r['symbol'] for r in rows})
        reasons: Counter[str]=Counter();technical=economic=0
        for row in rows:
            payload=row['payload_json'];payload=json.loads(payload) if isinstance(payload,str) else payload
            evidence=payload.get('evidence',{});technical+=bool(evidence.get('technical_eligible'));economic+=bool(evidence.get('economic_eligible'))
            reasons.update(evidence.get('reasons',[]))
        orders=[r for r in ledger.get('orders',[]) if r['created_at'][:13]==hour]
        fills=[r for r in ledger.get('fills',[]) if r['created_at'][:13]==hour]
        discovery=[]
        for db in bundle['databases']:
            for state in db.get('states',[]):
                if state['key'].startswith('raoe_discovery:') and state['updated_at'][:13]==hour:
                    p=state['payload_json'];p=json.loads(p) if isinstance(p,str) else p
                    discovery.extend(p.get('rows',[]))
        deferred=sorted({r['symbol'] for r in discovery if r.get('status') in {'DEFERRED','UNSCANNED'}})
        lines.extend([f'## {hour}:00 UTC','',f"Evaluated {len(rows)} strategy observations across {', '.join(symbols)}. Technical qualifications: {technical}; economic qualifications: {economic}.",
            f"Original blockers: {', '.join(f'{k} ({v})' for k,v in reasons.most_common(8)) or 'none recorded'}.",
            f"Paper orders: {len(orders)}; fills: {len(fills)}. These counts are ledger observations, not independent market episodes.",
            f"Deferred/unexamined in saved discovery cycles: {', '.join(deferred) or 'not established by saved discovery evidence'}.",
            'Alternative strategy outcomes and future executable depth require a separate version-pinned replay; a later rising price is insufficient evidence.',''])
    lines.extend(['## Financial and evidence limits','',f"Registered ledgers: {len(bundle['databases'])}; cross-database snapshots have separate cutoffs.",
        'The collector uses read-only SQL and Docker metadata. It does not access credentials or process environments. Truncated sections and missing historical depth must be retained in any independent analysis.',''])
    return '\n'.join(lines)


def main() -> None:
    from v491_diagnostics import main as streamed_main
    streamed_main()


if __name__=='__main__':main()
