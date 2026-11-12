#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
root=/opt/personal-plan/staging/integrations
remote=(ssh -o BatchMode=yes -o ConnectTimeout=10 aruba-vps)
helper=deploy/stockswatch/aruba_cutover.py

case "${1:-}" in
  --preflight)
    [[ $# == 1 ]]
    "${remote[@]}" python3 - --preflight < "$helper"
    ;;
  --deploy)
    [[ $# == 3 && "$2" =~ ^[0-9a-f]{40}$ ]] || exit 2
    commit=$2
    bundle=$3
    # Verify the reviewed bundle locally before uploading anything.
    read -r source_sha image_sha image_id < <(python3 "$helper" --verify-bundle "$bundle" "$commit")
    [[ "$source_sha" =~ ^[0-9a-f]{64}$ && "$image_sha" =~ ^[0-9a-f]{64}$ &&
       "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
    "${remote[@]}" python3 - --preflight < "$helper"
    state=$("${remote[@]}" "umask 077; mktemp -d '$root/stockswatch-${commit:0:12}.XXXXXXXX'")
    [[ "$state" == "$root/stockswatch-${commit:0:12}."* && "$state" =~ ^[a-zA-Z0-9/_.-]+$ ]]
    echo "Aruba release state $state"
    scp -q -o BatchMode=yes "$bundle/source.tar.gz" "$bundle/image.tar.gz" "aruba-vps:$state/"
    "${remote[@]}" python3 - --deploy "$state" "$commit" "$source_sha" "$image_sha" "$image_id" < "$helper"
    ;;
  *)
    echo "Usage: $0 --preflight | --deploy FULL_REVIEWED_SHA /absolute/path/to/release-bundle" >&2
    exit 2
    ;;
esac
