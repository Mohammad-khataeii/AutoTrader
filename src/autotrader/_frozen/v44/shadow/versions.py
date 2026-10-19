"""Execution identity is separate from API/application provenance."""

from __future__ import annotations

import builtins
import importlib
import importlib.abc
import importlib.util
import json
import sys
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from autotrader.research.data import canonical, digest

LEGACY_SOURCE = "9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a"
PREFIX = "autotrader._frozen.v42"
ROOT = Path(__file__).parents[1]
FROZEN = ROOT / "_frozen" / "v42"
# Conservative closure: execution, accounting, indicators and persistence all matter.
# API, diagnostics, transport scheduling and research publication do not authorize orders.
EXECUTION_FILES = (
    "clock.py",
    "config.py",
    "market_data/service.py",
    "scanner.py",
    "domain.py",
    "indicators.py",
    "decision.py",
    "risk.py",
    "portfolio.py",
    "strategies.py",
    "execution_gateway.py",
    "position_manager.py",
    "allocation.py",
    "shadow/runtime.py",
    "shadow/repository.py",
    "shadow/versions.py",
    "research/context.py",
    "research/experimental.py",
    "research/strategies.py",
    "research/regimes.py",
)


def execution_fingerprint() -> str:
    paths = {p for p in EXECUTION_FILES if (ROOT / p).is_file()}
    paths.update(
        str(p.relative_to(ROOT))
        for folder in ("execution", "persistence")
        for p in (ROOT / folder).rglob("*.py")
    )
    return digest(canonical({p: digest((ROOT / p).read_bytes()) for p in sorted(paths)}))


def verify_legacy() -> dict[str, str]:
    manifest = json.loads((FROZEN.parent / "v42-manifest.json").read_text())
    actual = {
        str(p.relative_to(FROZEN)): digest(p.read_bytes()) for p in sorted(FROZEN.rglob("*.py"))
    }
    if actual != manifest["files"] or digest(canonical(actual)) != LEGACY_SOURCE:
        raise ValueError("legacy_runtime_integrity_failed")
    return actual


def compatibility(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("execution_fingerprint"):
        valid = manifest["execution_fingerprint"] == execution_fingerprint()
        return {
            "compatible": valid,
            "runner": "native-v44",
            "reason": None if valid else "execution_implementation_changed",
        }
    if manifest.get("source_fingerprint") == LEGACY_SOURCE:
        try:
            verify_legacy()
            return {"compatible": True, "runner": "verified-v42", "reason": None}
        except ValueError as exc:
            return {"compatible": False, "runner": "verified-v42", "reason": str(exc)}
    return {"compatible": False, "runner": None, "reason": "unknown_frozen_runtime"}


class _FrozenLoader(importlib.abc.Loader):
    def __init__(self, path: Path):
        self.path = path

    def create_module(self, spec: Any) -> Any:
        return None

    def exec_module(self, module: Any) -> None:
        original = builtins.__import__

        def scoped_import(
            name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0
        ) -> Any:
            if level == 0 and (name == "autotrader" or name.startswith("autotrader.")):
                mapped = PREFIX + name[len("autotrader") :]
                result = original(mapped, globals, locals, fromlist, level)
                return result if fromlist else sys.modules[PREFIX]
            return original(name, globals, locals, fromlist, level)

        module.__dict__["__builtins__"] = {**vars(builtins), "__import__": scoped_import}
        # Original bytes, original filenames, original source fingerprint. Only
        # package imports are namespaced to prevent current modules leaking in.
        exec(compile(self.path.read_bytes(), str(self.path), "exec"), module.__dict__)  # noqa: S102 - hash-verified repository source, never external input.


class _FrozenFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname != PREFIX and not fullname.startswith(PREFIX + "."):
            return None
        relative = fullname[len(PREFIX) :].lstrip(".").replace(".", "/")
        directory = FROZEN / relative
        file = directory / "__init__.py" if directory.is_dir() else directory.with_suffix(".py")
        if not file.is_file():
            raise ImportError("Missing verified runtime module: " + fullname)
        return importlib.util.spec_from_file_location(
            fullname,
            file,
            loader=_FrozenLoader(file),
            submodule_search_locations=[str(directory)] if directory.is_dir() else None,
        )


_finder = _FrozenFinder()


def legacy_module(name: str) -> Any:
    verify_legacy()
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)
    return importlib.import_module(PREFIX + "." + name)


def convert(value: Any, legacy: bool = True) -> Any:
    """Copy shared observations across the isolated type boundary; no network I/O."""
    module = type(value).__module__
    prefix = "autotrader" if legacy else PREFIX
    if (is_dataclass(value) or isinstance(value, Enum)) and (
        module == prefix or module.startswith(prefix + ".")
    ):
        suffix = module[len(prefix) :].lstrip(".")
        target = (
            (sys.modules.get(PREFIX + "." + suffix) or legacy_module(suffix))
            if legacy
            else importlib.import_module("autotrader." + suffix)
        )
        cls = getattr(target, type(value).__name__)
        if isinstance(value, Enum):
            return cls(value.value)
        return cls(
            **{f.name: convert(getattr(value, f.name), legacy) for f in fields(value) if f.init}
        )
    if isinstance(value, dict):
        return {k: convert(v, legacy) for k, v in value.items()}
    if isinstance(value, list):
        return [convert(v, legacy) for v in value]
    if isinstance(value, tuple):
        return tuple(convert(v, legacy) for v in value)
    return value
