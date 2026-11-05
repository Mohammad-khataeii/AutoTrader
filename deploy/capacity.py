"""Read-only capacity estimates and backup retention inventory for staging."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

GIB = 1024**3


def filesystem(path: Path) -> tuple[int, int]:
    path = path.resolve()
    while not path.exists():
        path = path.parent
    return path.stat().st_dev, shutil.disk_usage(path).free


def forecast(database_sizes, *, backup_fs, docker_fs, transfer_fs, image_bytes,
             transfer_bytes, restore=True, extra_temp_bytes=GIB, reserve_bytes=GIB):
    """Budget at peak coexistence, combining reservations on shared filesystems."""
    if not database_sizes or any(type(n) is not int or n <= 0 for n in database_sizes.values()):
        raise ValueError("complete_positive_database_sizes_required")
    if any(type(n) is not int or n < 0 for n in (image_bytes, transfer_bytes, extra_temp_bytes, reserve_bytes)):
        raise ValueError("nonnegative_capacity_budgets_required")
    size = sum(database_sizes.values())
    # No compression credit. Keep the existing clone check's 2x size + dump rule.
    dump = (size*115+99)//100
    clone = max(GIB, 2*size+dump) if restore else 0
    devices = {}
    for (device, free), name, budget in (
        (backup_fs, "backup_dump", dump),
        (docker_fs, "isolated_restore", clone),
        (docker_fs, "unpacked_candidate_images", image_bytes),
        (docker_fs, "database_and_image_temporary_files", extra_temp_bytes),
        (transfer_fs, "transferred_artifacts", transfer_bytes),
    ):
        if free < 0:
            raise ValueError("invalid_filesystem_free_space")
        row = devices.setdefault(device, {"free_bytes": free, "reservations": {}})
        row["free_bytes"] = min(row["free_bytes"], free)
        row["reservations"][name] = budget
    for row in devices.values():
        row["required_bytes"] = sum(row["reservations"].values())+reserve_bytes
        row["shortfall_bytes"] = max(0, row["required_bytes"]-row["free_bytes"])
    shortfall = sum(r["shortfall_bytes"] for r in devices.values())
    return {"schema":"staging-capacity/1","status":"INSUFFICIENT_CAPACITY" if shortfall else "ESTIMATED_CAPACITY_AVAILABLE",
            "database_count":len(database_sizes),"database_sizes_bytes":database_sizes,
            "required_bytes":sum(r["required_bytes"] for r in devices.values()),
            "available_bytes":sum(r["free_bytes"] for r in devices.values()),
            "shortfall_bytes":shortfall,"filesystems":devices,
            "assumptions":{"dump_allowance_bytes":dump,"isolated_restore_bytes":clone,
                           "free_reserve_per_filesystem":reserve_bytes,"existing_backups_count_as_used":True},
            "restore_verification_still_required":True}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def verified_backup(manifest_path: Path, proof_path: Path) -> dict:
    """Validate complete dump bytes and immutable proof binding on local storage."""
    manifest_path=manifest_path.resolve(strict=True)
    manifest=json.loads(manifest_path.read_bytes())
    proof=json.loads(proof_path.read_bytes())
    if (manifest.get("schema")!="aruba-staging-backup/1" or manifest.get("project")!="autotrader-aruba-test"
            or proof.get("backup_manifest_sha256")!=sha256(manifest_path)
            or proof.get("restore_test") is not True or proof.get("network_internal") is not True
            or proof.get("source_databases_restored") is not False
            or proof.get("restore",{}).get("read_only_restore_verification") is not True
            or proof["restore"].get("status")!="PASS"):
        raise ValueError("backup_restore_proof_invalid_or_not_bound")
    records=manifest["databases"]
    accounts={r["account_id"] for r in records}
    restored={r["account_id"] for r in proof["restore"]["accounts"]
              if r.get("financial_seals")=="MATCH" and r.get("reconciliation")==[]}
    if (len(records)!=len(accounts) or len({r["database"] for r in records})!=len(records)
            or accounts!=restored or not {"paper-eur","PERSONAL_PLAN_PAPER_7000"}<=accounts):
        raise ValueError("backup_restore_account_coverage_mismatch")
    dump_bytes=0
    for record in records:
        dump=(manifest_path.parent/record["file"]).resolve(strict=True)
        if (dump.parent!=manifest_path.parent or dump.stat().st_size!=record["bytes"]
                or sha256(dump)!=record["sha256"] or not record["financial_seal"]):
            raise ValueError("backup_dump_missing_or_unverified")
        dump_bytes+=record["bytes"]
    return {"status":"VERIFIED_BACKUP_AND_RESTORE_PROOF","manifest_sha256":sha256(manifest_path),
            "dump_bytes":dump_bytes,"accounts":sorted(accounts),
            "database_dump_hashes":{r["database"]:r["sha256"] for r in records}}


def retention_plan(backup_root: Path, external_sets):
    """Classify only identical independent copies. Keep newer or unproven data."""
    external={}
    for manifest,proof in external_sets:
        if manifest.resolve().stat().st_dev==backup_root.stat().st_dev:
            raise ValueError("external_recovery_copy_must_use_independent_volume")
        result=verified_backup(manifest,proof)
        external[result["manifest_sha256"]]=result
    rows=[]
    for manifest in sorted(backup_root.glob("*/backup-set.json")):
        if manifest.resolve().parent.parent!=backup_root.resolve():
            continue
        identity=sha256(manifest)
        body=json.loads(manifest.read_bytes())
        records=body.get("databases",[])
        matching=external.get(identity)
        rows.append({"manifest":str(manifest),"created_at":body.get("created_at"),"manifest_sha256":identity,
                     "database_count":len(records),"recorded_dump_bytes":sum(r.get("bytes",0) for r in records),
                     "recommendation":"REVIEW_REDUNDANT_IDENTICAL_LOCAL_COPY" if matching else "RETAIN_NO_VERIFIED_EXTERNAL_COPY",
                     "delete_authorized":False})
    newest=max((r.get("created_at") or "" for r in rows),default="")
    for row in rows:
        if (row.get("created_at") or "")==newest:
            row["recommendation"]="KEEP_MOST_RECENT_LOCAL_SET"
    return {"status":"DRY_RUN","backup_sets":rows,"images":"Inventory image references separately from running and rollback containers.",
            "automated_deletion":False}


def artifact_plan(inventory, staging_root: Path):
    """Review staged artifacts from an operator-provided reference inventory."""
    import re

    incoming=(staging_root/"incoming").resolve()
    protected=set(inventory["referenced_image_ids"])
    complete=inventory.get("references_complete") is True
    images=[]
    for image in inventory["images"]:
        identity=image["id"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}",identity):
            raise ValueError("canonical_image_configuration_id_required")
        reason="KEEP_REFERENCED_OR_UNPROVEN"
        if complete and identity not in protected and image.get("recovery_copy_verified") is True:
            reason="REVIEW_UNREFERENCED_IMAGE"
        images.append({"id":identity,"bytes":image["bytes"],"recommendation":reason})
    transfers=[]
    for artifact in inventory["transfers"]:
        path=Path(artifact["path"]).resolve(strict=True)
        if not path.is_relative_to(incoming) or not path.is_file():
            raise ValueError("artifact_outside_staging_incoming")
        reason="KEEP_REFERENCED_OR_UNPROVEN"
        if complete and artifact.get("referenced") is False and artifact.get("external_copy"):
            external=Path(artifact["external_copy"]).resolve(strict=True)
            if external.stat().st_dev!=path.stat().st_dev and sha256(external)==sha256(path):
                reason="REVIEW_REDUNDANT_TRANSFER_COPY"
        transfers.append({"path":str(path),"bytes":path.stat().st_size,"recommendation":reason})
    return {"status":"DRY_RUN","images":images,"transfers":transfers,"automated_deletion":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="action",required=True)
    p=sub.add_parser("forecast")
    p.add_argument("inventory",type=Path,help="JSON mapping of database names to bytes")
    p.add_argument("--backup-path",type=Path,required=True)
    p.add_argument("--docker-path",type=Path,required=True)
    p.add_argument("--transfer-path",type=Path,required=True)
    p.add_argument("--image-bytes",type=int,required=True)
    p.add_argument("--transfer-bytes",type=int,required=True)
    p=sub.add_parser("verify-backup")
    p.add_argument("manifest",type=Path)
    p.add_argument("proof",type=Path)
    p=sub.add_parser("retention")
    p.add_argument("backup_root",type=Path)
    p.add_argument("--external",nargs=2,type=Path,action="append",default=[],metavar=("MANIFEST","PROOF"))
    p=sub.add_parser("artifacts")
    p.add_argument("inventory",type=Path)
    p.add_argument("--staging-root",type=Path,required=True)
    args=parser.parse_args()
    if args.action=="forecast":
        result=forecast(json.loads(args.inventory.read_bytes()),backup_fs=filesystem(args.backup_path),
                        docker_fs=filesystem(args.docker_path),transfer_fs=filesystem(args.transfer_path),
                        image_bytes=args.image_bytes,transfer_bytes=args.transfer_bytes)
    elif args.action=="verify-backup":
        result=verified_backup(args.manifest,args.proof)
    elif args.action=="retention":
        result=retention_plan(args.backup_root,args.external)
    else:
        result=artifact_plan(json.loads(args.inventory.read_bytes()),args.staging_root)
    print(json.dumps(result,indent=2))
    if result["status"]=="INSUFFICIENT_CAPACITY":
        raise SystemExit(2)


if __name__=="__main__":
    main()
