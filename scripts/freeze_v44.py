"""Reproduce the immutable V4.4 package from Git, never from current source."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

BASELINE = "ab742ee56c4774fb9a7b111f1f1043575f1743c9"
EXPECTED = "34ebd92039f48f786fe6bdf1d2f55a3c8430490ef6b4b7e6d129217000ee5890"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    prefix = "src/autotrader/"
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", BASELINE, prefix], cwd=ROOT
    ).decode().splitlines()
    source = {
        name.removeprefix(prefix): subprocess.check_output(
            ["git", "show", BASELINE + ":" + name], cwd=ROOT
        )
        for name in names if name.endswith(".py") and "/_frozen/" not in name
    }
    tree = ast.parse(source["shadow/versions.py"])
    closure = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "EXECUTION_FILES" for t in node.targets))
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(source.items())}
    execution = {name: value for name, value in hashes.items()
                 if name in closure or name.startswith(("execution/", "persistence/"))}
    # The original canonical() uses sorted keys and compact JSON separators.
    fingerprint = hashlib.sha256(json.dumps(execution, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if fingerprint != EXPECTED:
        raise RuntimeError("historical_v44_execution_identity_not_reproduced")
    destination = ROOT / "src/autotrader/_frozen/v44"
    for name, data in source.items():
        target = destination / name
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError("refusing_to_replace_frozen_source:" + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {"schema": "immutable-v44-runtime/1", "git_commit": BASELINE,
                "execution_fingerprint": fingerprint, "execution_files": execution, "files": hashes}
    (destination.parent / "v44-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"execution_fingerprint": fingerprint, "files": len(hashes)}))


if __name__ == "__main__":
    main()
