#!/usr/bin/env bash
# Verify a deployed Mnemo instance end to end.
#
#   ./scripts/verify_deployment.sh https://mnemo-xxxx.onrender.com
#
# Checks the health surface, per-visitor isolation and a real agent turn.
# The agent turn spends a small number of tokens. Pass --no-chat to skip it.
set -uo pipefail

BASE="${1:-}"
RUN_CHAT=1
[ "${2:-}" = "--no-chat" ] && RUN_CHAT=0
if [ -z "$BASE" ]; then
  echo "usage: $0 <url> [--no-chat]" >&2
  exit 2
fi
BASE="${BASE%/}"

PY="$(dirname "$0")/../.venv/bin/python"
[ -x "$PY" ] || PY="python3"
FAILED=0
pass() { echo "  PASS  $1${2:+ -- $2}"; }
fail() { echo "  FAIL  $1${2:+ -- $2}"; FAILED=$((FAILED+1)); }
check() { if [ "$1" = "1" ]; then pass "$2" "${3:-}"; else fail "$2" "${3:-}"; fi; }

echo "verifying $BASE"
echo
echo "reachability (a cold free instance can take ~60s to wake)"
CODE="$(curl -s -o /tmp/h.json -w '%{http_code}' --max-time 120 "$BASE/api/health")"
check "$([ "$CODE" = "200" ] && echo 1 || echo 0)" "health endpoint responds" "HTTP $CODE"
if [ "$CODE" != "200" ]; then
  echo; echo "Cannot continue: the service did not return a healthy response."; exit 1
fi

echo
echo "configuration"
eval "$("$PY" - <<'PYEOF'
import json
h = json.load(open("/tmp/h.json"))
def q(v): return str(v).replace("'", "")
print(f"DEMO={int(bool(h.get('demo_mode')))}")
print(f"NEB={int(bool(h.get('nebius_configured')))}")
print(f"TAV={int(bool(h.get('tavily_configured')))}")
print(f"FAST='{q(h.get('model_fast'))}'")
print(f"DEEP='{q(h.get('model_deep'))}'")
print(f"SKILLS={len(h.get('skills') or [])}")
print(f"LEFT='{q(h.get('turns_left'))}'")
PYEOF
)"
check "$NEB" "NEBIUS_API_KEY is set on the host"
check "$TAV" "TAVILY_API_KEY is set on the host" "needed for the Tavily prize"
check "$DEMO" "demo mode is on" "turns left: $LEFT"
check "$([ "$SKILLS" -ge 2 ] && echo 1 || echo 0)" "skills loaded" "$SKILLS found"
check "$([ "$FAST" = "nvidia/Nemotron-3_5-Lightning" ] && echo 1 || echo 0)" "fast model is Nemotron Lightning" "$FAST"
check "$([ "$DEEP" = "nvidia/Nemotron-3-Ultra-550b-a55b" ] && echo 1 || echo 0)" "reasoning model is Nemotron Ultra" "$DEEP"

echo
echo "the page a judge will open"
for path in "/" "/static/app.js" "/static/styles.css"; do
  c="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$BASE$path")"
  check "$([ "$c" = "200" ] && echo 1 || echo 0)" "GET $path" "HTTP $c"
done

echo
echo "per-visitor isolation"
A=/tmp/va.txt; B=/tmp/vb.txt; rm -f $A $B
curl -s -c $A -b $A -X POST "$BASE/api/memories" -H 'Content-Type: application/json' \
  -d '{"text":"Visitor A deployment check note."}' -o /dev/null --max-time 30
curl -s -c $B -b $B -X POST "$BASE/api/memories" -H 'Content-Type: application/json' \
  -d '{"text":"Visitor B deployment check note."}' -o /dev/null --max-time 30
SEEN="$(curl -s -c $A -b $A "$BASE/api/memories" --max-time 30 | "$PY" -c "import json,sys; print(sum('Visitor B' in m['text'] for m in json.load(sys.stdin)['memories']))")"
check "$([ "$SEEN" = "0" ] && echo 1 || echo 0)" "visitor A cannot see visitor B's memories"
BID="$(curl -s -c $B -b $B "$BASE/api/memories" --max-time 30 | "$PY" -c "import json,sys; m=json.load(sys.stdin)['memories']; print(m[0]['id'] if m else '')")"
if [ -n "$BID" ]; then
  DC="$(curl -s -o /dev/null -w '%{http_code}' -c $A -b $A -X DELETE "$BASE/api/memories/$BID" --max-time 30)"
  check "$([ "$DC" = "404" ] && echo 1 || echo 0)" "visitor A cannot delete visitor B's memory" "HTTP $DC"
fi
curl -s -c $A -b $A -X POST "$BASE/api/memories/wipe" -o /dev/null --max-time 30
STILL="$(curl -s -c $B -b $B "$BASE/api/memories" --max-time 30 | "$PY" -c "import json,sys; print(len(json.load(sys.stdin)['memories']))")"
check "$([ "$STILL" -ge 1 ] && echo 1 || echo 0)" "visitor A's wipe left visitor B untouched"
curl -s -c $B -b $B -X POST "$BASE/api/memories/wipe" -o /dev/null --max-time 30
rm -f $A $B

if [ "$RUN_CHAT" = "1" ]; then
  echo
  echo "a real agent turn through Token Factory"
  C=/tmp/vc.txt; rm -f $C
  curl -s -c $C -b $C -X POST "$BASE/api/chat" -H 'Content-Type: application/json' \
    -d '{"message":"Remember that I am verifying the Mnemo deployment."}' \
    -o /tmp/chat.json --max-time 180
  eval "$("$PY" - <<'PYEOF'
import json
try:
    d = json.load(open("/tmp/chat.json"))
except Exception:
    print("OK=0; TOOLS=''; REPLY=''; MODELS=''"); raise SystemExit
tools = [e.get("tool") for e in d.get("events") or []]
print(f"OK={int(bool(d.get('reply')))}")
print(f"TOOLS='{','.join(t for t in tools if t) or 'none'}'")
print(f"MODELS='{','.join(d.get('models_used') or [])}'")
print(f"REPLY='{(d.get('reply') or d.get('detail') or '')[:70].replace(chr(39),'')}'")
PYEOF
)"
  check "$OK" "the agent replied" "$REPLY"
  check "$([ "${TOOLS#*remember}" != "$TOOLS" ] && echo 1 || echo 0)" "it called the remember tool" "tools: $TOOLS"
  check "$([ -n "$MODELS" ] && echo 1 || echo 0)" "served by Nemotron on Token Factory" "$MODELS"
  LEFT2="$("$PY" -c "import json; print(json.load(open('/tmp/chat.json')).get('turns_left'))" 2>/dev/null)"
  check "$([ "$LEFT2" != "None" ] && [ -n "$LEFT2" ] && echo 1 || echo 0)" "demo budget is counting down" "turns left: $LEFT2"
  curl -s -c $C -b $C -X POST "$BASE/api/memories/wipe" -o /dev/null --max-time 30
  rm -f $C
fi

echo
if [ "$FAILED" -gt 0 ]; then
  echo "$FAILED check(s) failed."; exit 1
fi
echo "deployment verified: $BASE"
