#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "${1:-}" == "--preflight" ]]; then
  MODE=preflight
  SHA="${2:-}"
else
  MODE=deploy
  SHA="${1:-}"
fi
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Usage: bash deploy_crypto_micro.sh [--preflight] FULL_PINNED_40_CHAR_GITHUB_SHA" >&2
  exit 2
}
for prog in curl ssh tar python3; do
  command -v "$prog" >/dev/null || { echo "Missing $prog" >&2; exit 2; }
done
HOST="${ARUBA_SSH_HOST:-aruba-vps}"
ROOT_URL="https://raw.githubusercontent.com/Mohammad-khataeii/AutoTrader/$SHA"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/autotrader-crypto-micro.XXXXXXXX")"
trap 'rm -rf "$WORK"' EXIT
FILES=(
  stockswatch/alpaca_crypto.py
  stockswatch/alpaca_crypto_paper.py
  stockswatch/crypto_active_paper.py
  stockswatch/crypto_micro.py
  deploy/stockswatch/Dockerfile.crypto_micro
  deploy/stockswatch/crypto_micro_cutover.py
)

echo "1/4 Downloading only the pinned crypto overlay at $SHA"
for file in "${FILES[@]}"; do
  mkdir -p "$WORK/$(dirname "$file")"
  curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors \
    --connect-timeout 15 --max-time 180 \
    "$ROOT_URL/$file" -o "$WORK/$file"
done
python3 - "$WORK" "$SHA" <<'PY'
import hashlib,json,os,sys
from pathlib import Path
root=Path(sys.argv[1]);revision=sys.argv[2]
paths=["stockswatch/alpaca_crypto.py","stockswatch/alpaca_crypto_paper.py",
"stockswatch/crypto_active_paper.py","stockswatch/crypto_micro.py",
"deploy/stockswatch/Dockerfile.crypto_micro",
"deploy/stockswatch/crypto_micro_cutover.py"]
import ast
for p in paths:
    if p.endswith(".py"):
        ast.parse((root/p).read_text(encoding="utf-8"),filename=p)
record={"commit":revision,"files":{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}}
(root/"manifest.json").write_text(json.dumps(record,indent=2))
print("Pinned source downloaded and Python syntax verified")
PY

echo "2/4 Sending exact source and manifest to Aruba"
STAGE="$(ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 \
  "$HOST" "umask 077; mktemp -d '/opt/personal-plan/staging/integrations/crypto-micro-${SHA:0:12}.XXXXXXXX'")"
[[ "$STAGE" =~ ^/opt/personal-plan/staging/integrations/crypto-micro-[0-9a-f]{12}\.[A-Za-z0-9]+$ ]] || {
  echo "Unexpected remote directory" >&2; exit 1;
}
tar -C "$WORK" -cf - . | ssh -o BatchMode=yes -o ServerAliveInterval=30 "$HOST" \
  "tar -xf - -C '$STAGE'"

echo "3/4 Read-only paper broker / ledger / source / stock session preflight"
ssh -o BatchMode=yes -o ServerAliveInterval=30 "$HOST" \
  "python3 '$STAGE/deploy/stockswatch/crypto_micro_cutover.py' preflight '$STAGE' '$SHA'"
if [[ "$MODE" == preflight ]]; then
  echo "Preflight passed. No container or orders changed."
  exit 0
fi

echo "4/4 Building from EXISTING image and cutover ONLY StocksWatch, with rollback"
ssh -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=20 "$HOST" \
  "python3 '$STAGE/deploy/stockswatch/crypto_micro_cutover.py' deploy '$STAGE' '$SHA'"
echo "Release evidence and backups kept on Aruba at $STAGE"
