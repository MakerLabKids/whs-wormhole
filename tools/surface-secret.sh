#!/bin/bash
# surface-secret.sh NAME: print one Surface secret's value from the repo's .env, with no newline,
# for piping straight into wrangler so it is never shown on screen:
#
#   cd cloud/surface
#   ../../tools/surface-secret.sh ENROL_SECRET  | npx wrangler secret put ENROL_SECRET
#   ../../tools/surface-secret.sh TUNNEL_TOKENS | npx wrangler secret put TUNNEL_TOKENS
#
# ENROL_SECRET  = .env enrol_secret (the same value is on every Pi at /etc/burrow/enrol.secret;
#                 a cloned card proves it is one of ours with it)
# TUNNEL_TOKENS = .env TUNNEL_TOKENS, JSON {"burrow0": "<cloudflared token>", ...}: the Surface hands a
#                 newly enrolled Pi its room's token so its cloudflared comes up as burrowN
set -euo pipefail
ENV="$(cd "$(dirname "$0")/.." && pwd)/.env"
case "${1:-}" in
  ENROL_SECRET) key=enrol_secret ;;
  TUNNEL_TOKENS) key=TUNNEL_TOKENS ;;
  *) echo "usage: $0 ENROL_SECRET|TUNNEL_TOKENS" >&2; exit 2 ;;
esac
python3 - "$ENV" "$key" <<'PY'
import re, sys, json
for line in open(sys.argv[1]):
    m = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line.rstrip('\n'))
    if m and m.group(1) == sys.argv[2]:
        v = m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'': v = v[1:-1]
        if sys.argv[2] == 'TUNNEL_TOKENS': json.loads(v)          # refuse to upload a non-JSON value
        sys.stdout.write(v); sys.exit(0)
sys.exit('%s is not in %s' % (sys.argv[2], sys.argv[1]))
PY
