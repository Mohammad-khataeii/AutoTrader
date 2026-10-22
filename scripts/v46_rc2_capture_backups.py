"""Stream SELECT-only PostgreSQL dumps to a private local directory; no VPS files."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def main() -> None:
    inventory = json.loads(Path(".tools/v46-rc2-production-current.json").read_text())
    records = inventory["accounts"]
    assert len(records) == 9 and len({r["database_name"] for r in records}) == 9
    assert all(r["state"] != "CREATING" and not r["reconciliation"] for r in records)
    destination = Path(".tools/v46-rc2-backups") / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    destination.mkdir(parents=True, mode=0o700)
    report = {"evidence_class": "REAL_PRODUCTION_READ_ONLY_OBSERVATION", "remote_files_created": False,
              "captured_at": datetime.now(UTC).isoformat(), "databases": []}
    for record in records:
        name = record["database_name"]
        assert name == "autotrader" or re.fullmatch(r"autotrader_shadow_[a-f0-9]{32}", name)
        path = destination / (name + ".dump")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            subprocess.run(["ssh", "-o", "BatchMode=yes", "autotrader-vps",
                "cd /home/ubuntu/autotrader && docker compose -p autotrader-v41 exec -T postgres pg_dump -U autotrader --serializable-deferrable -Fc " + name],
                stdout=output, check=True)
        data = path.read_bytes()
        report["databases"].append({"database": name, "account_id": "paper-eur" if record["identity"] == "official" else "shadow:" + record["identity"],
            "manifest_hash": record["manifest_hash"], "manifest": record["manifest"], "state": record["state"], "archive": record["archive"],
            "file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        print(name + ": " + str(len(data)) + " bytes", flush=True)
    (destination / "backup-set.json").write_text(json.dumps(report, indent=2) + "\n")
    Path(".tools/v46-rc2-backup-path.txt").write_text(str(destination.resolve()) + "\n")
    print("Complete private local backup set: " + str(destination), flush=True)


if __name__ == "__main__":
    main()
