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
V44_EXECUTION = "34ebd92039f48f786fe6bdf1d2f55a3c8430490ef6b4b7e6d129217000ee5890"
V44_PACKAGE = "d7aec58e3c62595d77b96cd74dd11248dab40bdf9575eb50bb6c2b6e49ef8064"
FROZEN_V44 = ROOT / "_frozen" / "v44"
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
    "shadow/lab.py",
    "shadow/views.py",
    "worker/runner.py",
    "research/data.py",
    "research/artifacts.py",
    "market_data/replay.py",
    "shadow/legacy.py",
    "shadow/frozen.py",
    "shadow/trace.py",
    "shadow/diagnostics.py",
    "shadow/gates.py",
    "market_data/revolut.py",
    "market_data/scheduling.py",
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
    paths.add("shadow/v45-boundary.json")
    return digest(canonical({p: digest((ROOT / p).read_bytes()) for p in sorted(paths)}))


def verify_legacy() -> dict[str, str]:
    manifest = json.loads((FROZEN.parent / "v42-manifest.json").read_text())
    actual = {
        str(p.relative_to(FROZEN)): digest(p.read_bytes()) for p in sorted(FROZEN.rglob("*.py"))
    }
    if actual != manifest["files"] or digest(canonical(actual)) != LEGACY_SOURCE:
        raise ValueError("legacy_runtime_integrity_failed")
    return actual


BOUNDARY_FILES = ('config.py', 'domain.py', 'indicators.py', 'market_data/replay.py', 'market_data/revolut.py', 'market_data/scheduling.py', 'market_data/service.py', 'research/artifacts.py', 'research/context.py', 'research/data.py', 'scanner.py', 'shadow/diagnostics.py', 'shadow/frozen.py', 'shadow/gates.py', 'shadow/lab.py', 'shadow/legacy.py', 'shadow/runtime.py', 'shadow/trace.py', 'shadow/versions.py', 'shadow/views.py', 'worker/runner.py')


def verify_boundary() -> None:
    """Review-pinned bridge closure, separate from immutable V4.2 strategy bytes."""
    manifest = json.loads((ROOT / "shadow/v45-boundary.json").read_text())
    if set(manifest["files"]) != set(BOUNDARY_FILES):
        raise ValueError("legacy_observation_boundary_integrity_failed")
    actual = {name: digest((ROOT / name).read_bytes()) for name in BOUNDARY_FILES}
    if actual != manifest["files"]:
        raise ValueError("legacy_observation_boundary_integrity_failed")


def verify_v44() -> dict[str, str]:
    """Prove both the historical algorithm's closure and all imported dependencies."""
    manifest = json.loads((FROZEN_V44.parent / "v44-manifest.json").read_text())
    actual = {str(p.relative_to(FROZEN_V44)): digest(p.read_bytes())
              for p in sorted(FROZEN_V44.rglob("*.py"))}
    if actual != manifest["files"] or digest(canonical(actual)) != V44_PACKAGE:
        raise ValueError("v44_runtime_integrity_failed")
    execution = {name: actual[name] for name in manifest["execution_files"]}
    if execution != manifest["execution_files"] or digest(canonical(execution)) != V44_EXECUTION:
        raise ValueError("v44_execution_integrity_failed")
    return actual


def generation(manifest: dict[str, Any]) -> str | None:
    """Identity selects code; a user-facing version label never grants admission."""
    fingerprint = manifest.get("execution_fingerprint")
    if fingerprint == V44_EXECUTION:
        return "v44"
    if fingerprint:
        return "v45" if fingerprint == execution_fingerprint() else None
    return "v42" if manifest.get("source_fingerprint") == LEGACY_SOURCE else None


def compatibility(manifest: dict[str, Any]) -> dict[str, Any]:
    selected = generation(manifest)
    runner = {"v42": "verified-v42", "v44": "verified-v44", "v45": "native-v45"}.get(selected or "")
    if selected:
        try:
            if selected == "v44":
                verify_v44()
            elif selected == "v42":
                verify_legacy()
            verify_boundary()
            return {"compatible": True, "runner": runner, "reason": None}
        except (ValueError, OSError, KeyError) as exc:
            return {"compatible": False, "runner": runner, "reason": str(exc)}
    return {"compatible": False, "runner": None, "reason": "unknown_frozen_runtime"}


def verify_generation(selected: str) -> None:
    if selected == "v42":
        verify_legacy()
    elif selected == "v44":
        verify_v44()
    else:
        raise ValueError("unknown_frozen_runtime")
    verify_boundary()


class _FrozenLoader(importlib.abc.Loader):
    def __init__(self, path: Path, prefix: str = PREFIX):
        self.path, self.prefix = path, prefix

    def create_module(self, spec: Any) -> Any:
        return None

    def exec_module(self, module: Any) -> None:
        original = builtins.__import__

        def scoped_import(
            name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0
        ) -> Any:
            if level == 0 and (name == "autotrader" or name.startswith("autotrader.")):
                mapped = self.prefix + name[len("autotrader") :]
                result = original(mapped, globals, locals, fromlist, level)
                return result if fromlist else sys.modules[self.prefix]
            return original(name, globals, locals, fromlist, level)

        module.__dict__["__builtins__"] = {**vars(builtins), "__import__": scoped_import}
        # Original bytes, original filenames, original source fingerprint. Only
        # package imports are namespaced to prevent current modules leaking in.
        exec(compile(self.path.read_bytes(), str(self.path), "exec"), module.__dict__)  # noqa: S102 - hash-verified repository source, never external input.


class _FrozenFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        selected = next((g for g in ("v42", "v44")
                         if fullname == "autotrader._frozen." + g
                         or fullname.startswith("autotrader._frozen." + g + ".")), None)
        if selected is None:
            return None
        prefix = "autotrader._frozen." + selected
        relative = fullname[len(prefix) :].lstrip(".").replace(".", "/")
        directory = (FROZEN if selected == "v42" else FROZEN_V44) / relative
        file = directory / "__init__.py" if directory.is_dir() else directory.with_suffix(".py")
        if not file.is_file():
            raise ImportError("Missing verified runtime module: " + fullname)
        return importlib.util.spec_from_file_location(
            fullname,
            file,
            loader=_FrozenLoader(file, prefix),
            submodule_search_locations=[str(directory)] if directory.is_dir() else None,
        )


_finder = _FrozenFinder()


def legacy_module(name: str) -> Any:
    return frozen_module(name, "v42")


def frozen_module(name: str, selected: str) -> Any:
    if selected == "v42":
        verify_legacy()
    elif selected == "v44":
        verify_v44()
    else:
        raise ValueError("unknown_frozen_runtime")
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)
    return importlib.import_module("autotrader._frozen." + selected + "." + name)


def convert(value: Any, legacy: bool = True, selected: str = "v42") -> Any:
    """Copy shared observations across the isolated type boundary; no network I/O."""
    module = type(value).__module__
    frozen_prefix = "autotrader._frozen." + selected
    prefix = "autotrader" if legacy else frozen_prefix
    if (is_dataclass(value) or isinstance(value, Enum)) and (
        module == prefix or module.startswith(prefix + ".")
    ):
        suffix = module[len(prefix) :].lstrip(".")
        target = (
            (sys.modules.get(frozen_prefix + "." + suffix) or frozen_module(suffix, selected))
            if legacy
            else importlib.import_module("autotrader." + suffix)
        )
        cls = getattr(target, type(value).__name__)
        if isinstance(value, Enum):
            return cls(value.value)
        return cls(
            **{f.name: convert(getattr(value, f.name), legacy, selected) for f in fields(value) if f.init}
        )
    if isinstance(value, dict):
        return {k: convert(v, legacy, selected) for k, v in value.items()}
    if isinstance(value, list):
        return [convert(v, legacy, selected) for v in value]
    if isinstance(value, tuple):
        return tuple(convert(v, legacy, selected) for v in value)
    return value
