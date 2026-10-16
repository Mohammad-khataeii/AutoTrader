from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autotrader.research.data import canonical, digest


def source_fingerprint() -> tuple[str, dict[str, str]]:
    root = Path(__file__).parents[1]
    files = {str(path.relative_to(root)).replace("\\", "/"): digest(path.read_bytes()) for path in sorted(root.rglob("*.py"))}
    return digest(canonical(files)), files


def load_latest(root: Path, *, pointer_name: str = "latest-run.json") -> dict[str, Any] | None:
    if pointer_name not in {"latest-run.json", "latest-experimental-run.json"}:
        raise ValueError("unsupported_research_pointer")
    pointer = root / pointer_name
    if not pointer.exists():
        return None
    latest = json.loads(pointer.read_text(encoding="utf-8"))
    path = (root / str(latest["summary"]).replace("\\", "/")).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("research_summary_outside_store")
    payload = path.read_bytes()
    if digest(payload) != latest["summary_sha256"]:
        raise ValueError("research_summary_hash_mismatch")
    return dict(json.loads(payload))
