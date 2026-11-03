#!/usr/bin/env bash
# Transmit Version Management helper for the pipeline.
#   scripts/tsvm.sh build    <out.zip>   package journeys/ (+ sub-journeys/, connections/) as a selective ZIP
#   scripts/tsvm.sh validate <pkg.zip>   dry run on the tenant; fails unless the body says "status": "success"
#   scripts/tsvm.sh import   <pkg.zip> [backup.zip]   import with failureRollBack=true; with a backup export of
#                                       the SAME tenant, its application metadata is added to the package (some
#                                       tenants, e.g. DEV, fail the import without it; taken from the same tenant it
#                                       changes nothing there)
#   scripts/tsvm.sh export   <out.zip>   full journeys export of the tenant (backup / drift)
# Env: TS_CLIENT_ID, TS_CLIENT_SECRET, TS_TENANT_ID, TS_REGION (sbx | us | eu | ca | au | dev)
set -euo pipefail
cd "$(dirname "$0")/.."
CMD=${1:?command} FILE=${2:?file}

if [ "$CMD" = build ]; then
  TMP=$(mktemp -d); IDO=$TMP/exported-data/ido
  mkdir -p "$IDO"; printf "version: '5'\n" > "$IDO/manifest.yaml"
  for pair in journeys:journeys sub-journeys:sub-journeys connections:external-connections; do
    src=${pair%%:*} dst=${pair##*:}
    ls "$src"/*.yaml >/dev/null 2>&1 || continue
    mkdir -p "$IDO/$dst"; cp "$src"/*.yaml "$IDO/$dst/"
    printf "mode: selective\nnotFound: []\n" > "$IDO/$dst/manifest.yaml"
  done
  rm -f "$FILE"; (cd "$TMP" && zip -qr - exported-data) > "$FILE"; rm -rf "$TMP"
  echo "built $FILE"; exit 0
fi

: "${TS_CLIENT_ID:?}" "${TS_CLIENT_SECRET:?}" "${TS_TENANT_ID:?}" "${TS_REGION:?}"
case "$TS_REGION" in
  sbx) API=api.sbx.transmitsecurity.io; VM=version-management.sbx.transmitsecurity.io ;;
  us)  API=api.transmitsecurity.io;     VM=version-management.transmitsecurity.io ;;
  eu)  API=api.eu.transmitsecurity.io;  VM=version-management.eu.transmitsecurity.io ;;
  ca)  API=api.ca.transmitsecurity.io;  VM=version-management.ca.transmitsecurity.io ;;
  au)  API=api.au.transmitsecurity.io;  VM=version-management.au.transmitsecurity.io ;;
  dev) API=api.idsec-dev.com;           VM=version-management.idsec-dev.com ;;
  *) echo "unknown TS_REGION $TS_REGION" >&2; exit 1 ;;
esac

TOK=$(mktemp)
CODE=$(curl -s -m 60 -o "$TOK" -w '%{http_code}' -X POST "https://$API/oidc/token" \
  --data-urlencode "client_id=$TS_CLIENT_ID" --data-urlencode "client_secret=$TS_CLIENT_SECRET" \
  -d grant_type=client_credentials) || CODE="000 (connection failed: $API not reachable)"
TOKEN=$(python3 -c 'import sys,json;print(json.load(open(sys.argv[1])).get("access_token",""))' "$TOK" 2>/dev/null || true)
if [ -z "$TOKEN" ]; then
  echo "token request to $API failed: HTTP $CODE" >&2; head -c 300 "$TOK" >&2; echo >&2; rm -f "$TOK"; exit 1
fi
rm -f "$TOK"
URL="https://$VM/version"

if [ "$CMD" = export ]; then
  CODE=$(curl -s -o "$FILE" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$URL/export/$TS_TENANT_ID?format=zip")
  echo "export -> HTTP $CODE"; [[ $CODE == 2* ]] || { cat "$FILE"; echo; exit 1; }
  exit 0
fi

python3 scripts/guard.py "$FILE"
if [ "$CMD" = import ] && [ -n "${3:-}" ]; then
  python3 - "$FILE" "$3" <<'EOF'
import sys, zipfile
pkg, backup = sys.argv[1:]
with zipfile.ZipFile(backup) as b:
    meta = {n: b.read(n) for n in b.namelist() if n.startswith("exported-data/ido/metadata/") and n.endswith(".yaml")}
if not meta:
    sys.exit("no application metadata in the backup")
with zipfile.ZipFile(pkg) as p:
    items = {n: p.read(n) for n in p.namelist() if n not in meta}
with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as p:
    for n, data in {**items, **meta}.items():
        p.writestr(n, data)
print(f"added {len(meta)} metadata files from {backup}")
EOF
fi
case "$CMD" in
  validate) QS="format=zip" ;;
  import)   QS="format=zip&failureRollBack=true" ;;
  *) echo "unknown command $CMD" >&2; exit 1 ;;
esac
RESP=$(mktemp)
CODE=$(curl -s -o "$RESP" -w '%{http_code}' -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/zip' --data-binary "@$FILE" "$URL/$CMD/$TS_TENANT_ID?$QS")
echo "$CMD -> HTTP $CODE"
python3 -m json.tool "$RESP" 2>/dev/null || cat "$RESP"
# validate answers 201 even when it finds problems: the verdict is in the body
python3 - "$RESP" "$CODE" <<'EOF'
import sys, json
body, code = sys.argv[1], sys.argv[2]
try:
    status = json.load(open(body)).get("status")
except Exception:
    status = None
if not code.startswith("2") or status not in ("success", None):
    sys.exit(f"FAILED: HTTP {code}, status {status}")
EOF
