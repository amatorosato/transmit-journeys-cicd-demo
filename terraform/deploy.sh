#!/usr/bin/env bash
# Called by terraform/main.tf on apply: backup, guard, validate, import with rollback, check the tenant matches Git.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TS_CLIENT_ID:?missing: add TS_CLIENT_ID in the HCP workspace as an Environment variable (sensitive)}"
: "${TS_CLIENT_SECRET:?missing: add TS_CLIENT_SECRET in the HCP workspace as an Environment variable (sensitive)}"

WORK=$(mktemp -d)
# PyYAML is not installed on the HCP Terraform workers: install it for this run only
if ! python3 -c 'import yaml' 2>/dev/null; then
  python3 -m pip install -q --target "$WORK/pylib" pyyaml 2>/dev/null \
    || python3 -m pip install -q --break-system-packages --target "$WORK/pylib" pyyaml
  export PYTHONPATH="$WORK/pylib${PYTHONPATH:+:$PYTHONPATH}"
fi

STAGE=${TS_STAGE/production/prod} PREV_STAGE=${PREV_TS_STAGE:-}
PREV_STAGE=${PREV_STAGE/production/prod}
echo "== Deploying to the $STAGE tenant"

# Promotion gate: the previous stage must already run exactly this version. For prod the check is done when the
# deploy is requested ("Request prod deploy" checks the test tenant), because by deploy time the test tenant may
# already run newer versions of main.
if [ "$STAGE" = prod ]; then
  echo "== Promotion gate: checked when the prod deploy was requested (the test tenant ran this version)"
elif [ -n "${PREV_TS_TENANT_ID:-}" ]; then
  : "${PREV_TS_CLIENT_ID:?missing: add PREV_TS_CLIENT_ID in the HCP workspace as an Environment variable (sensitive)}"
  : "${PREV_TS_CLIENT_SECRET:?missing: add PREV_TS_CLIENT_SECRET in the HCP workspace as an Environment variable (sensitive)}"
  echo "== Promotion gate: the $PREV_STAGE tenant must already have this version"
  if ! ( export TS_CLIENT_ID="$PREV_TS_CLIENT_ID" TS_CLIENT_SECRET="$PREV_TS_CLIENT_SECRET" \
           TS_TENANT_ID="$PREV_TS_TENANT_ID" TS_REGION="$PREV_TS_REGION" \
           TS_TENANT_NAME="$PREV_TS_TENANT_NAME" TS_STAGE="$PREV_TS_STAGE"
         bash scripts/tsvm.sh export "$WORK/previous.zip" && python3 scripts/drift.py "$WORK/previous.zip" ); then
    echo "REFUSED: the $PREV_STAGE tenant does not have this version yet. Apply transmit-$PREV_STAGE first, then start a new run here." >&2
    exit 1
  fi
fi
echo "== Backup of the $STAGE tenant before the change"
bash scripts/tsvm.sh export "$WORK/backup.zip"
# with the backup, soft-deleted journeys no longer on this tenant are left out (never re-created)
bash scripts/tsvm.sh build "$WORK/package.zip" "$WORK/backup.zip"
python3 scripts/guard.py "$WORK/package.zip"
echo "== Validate"
bash scripts/tsvm.sh validate "$WORK/package.zip"
echo "== Import (rollback on failure)"
bash scripts/tsvm.sh import "$WORK/package.zip" "$WORK/backup.zip"
echo "== Check that the $STAGE tenant now matches Git"
bash scripts/tsvm.sh export "$WORK/after.zip"
python3 scripts/drift.py "$WORK/after.zip"
