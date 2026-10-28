#!/usr/bin/env bash
# Deploy Mnemo to a Hugging Face Space.
#
# A Space repo needs Dockerfile and a front-matter README.md at ITS root, which
# is not this repo's layout -- and adding HF front-matter to our own README
# would render as a stray table on GitHub. So we assemble the Space layout in a
# temp dir and push that.
#
#   HF_TOKEN=hf_xxx ./scripts/deploy_space.sh [space-name]
#
# The username is read from the token. Pass --dry-run to assemble and validate
# without touching the network.
#
# Note: creating a Docker Space on free cpu-basic hardware requires a PRO
# account. The script says so plainly if the API refuses.
set -euo pipefail

SPACE_NAME="mnemo"
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *) SPACE_NAME="$arg" ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

# ---- assemble ----
cp -R "$ROOT/app" "$ROOT/web" "$ROOT/skills" "$STAGE/"
cp "$ROOT/requirements.txt" "$ROOT/LICENSE" "$STAGE/"
cp "$ROOT/deploy/Dockerfile.space" "$STAGE/Dockerfile"
cp "$ROOT/deploy/README-space.md" "$STAGE/README.md"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "Space layout:"
(cd "$STAGE" && find . -type f | sort | sed 's/^/  /')

# ---- validate against the Space config rules ----
APP_PORT="$(awk -F': *' '/^app_port:/{print $2}' "$STAGE/README.md")"
if ! grep -q "\${PORT:-$APP_PORT}" "$STAGE/Dockerfile"; then
  echo "ERROR: README app_port ($APP_PORT) != the port the Dockerfile serves." >&2
  exit 1
fi
DESC_LEN=$(awk -F': *' '/^short_description:/{print substr($0, index($0,$2))}' "$STAGE/README.md" | tr -d '\n' | wc -c | tr -d ' ')
if [ "$DESC_LEN" -gt 60 ]; then
  echo "ERROR: short_description is $DESC_LEN chars; the Hub limit is 60." >&2
  exit 1
fi
grep -q '^sdk: docker' "$STAGE/README.md" || { echo "ERROR: README must declare 'sdk: docker'." >&2; exit 1; }
echo "OK: app_port $APP_PORT matches, short_description $DESC_LEN/60 chars, sdk docker."

if [ "$DRY_RUN" = "1" ]; then
  echo "Dry run: nothing pushed."
  exit 0
fi

if [ -z "${HF_TOKEN:-}" ]; then
  echo "ERROR: set HF_TOKEN (huggingface.co/settings/tokens, needs write access)." >&2
  exit 2
fi

api() { curl -sS -w '\n%{http_code}' -H "Authorization: Bearer $HF_TOKEN" "$@"; }

# ---- who are we ----
WHOAMI="$(api https://huggingface.co/api/whoami-v2)"
WHOAMI_CODE="$(printf '%s' "$WHOAMI" | tail -n1)"
if [ "$WHOAMI_CODE" != "200" ]; then
  echo "ERROR: the token was rejected (HTTP $WHOAMI_CODE). Check it has write access." >&2
  exit 1
fi
USER_NAME="$(printf '%s' "$WHOAMI" | sed '$d' | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
echo "Authenticated as $USER_NAME."

# ---- create the Space if it is not there yet ----
EXISTS="$(api -o /dev/null "https://huggingface.co/api/spaces/$USER_NAME/$SPACE_NAME" | tail -n1)"
if [ "$EXISTS" = "200" ]; then
  echo "Space $USER_NAME/$SPACE_NAME already exists; updating it."
else
  echo "Creating Space $USER_NAME/$SPACE_NAME ..."
  BODY="$(python3 -c '
import json, sys
print(json.dumps({"name": sys.argv[1], "type": "space", "sdk": "docker",
                  "private": False, "license": "mit"}))' "$SPACE_NAME")"
  RESP="$(api -X POST https://huggingface.co/api/repos/create \
          -H "Content-Type: application/json" -d "$BODY")"
  CODE="$(printf '%s' "$RESP" | tail -n1)"
  case "$CODE" in
    200|201|409) echo "Space ready." ;;
    402|403)
      echo "ERROR: Hugging Face refused to create a Docker Space (HTTP $CODE)." >&2
      echo "Creating Docker Spaces on free cpu-basic hardware requires a PRO account." >&2
      echo "Either upgrade at huggingface.co/pricing, or deploy to Render instead:" >&2
      echo "  render.yaml is at the repo root -- New -> Blueprint in the Render dashboard." >&2
      exit 1 ;;
    *)
      echo "ERROR: could not create the Space (HTTP $CODE):" >&2
      printf '%s\n' "$RESP" | sed '$d' >&2
      exit 1 ;;
  esac
fi

# ---- push ----
cd "$STAGE"
git init -q -b main
git add -A
git -c user.email="noreply@huggingface.co" -c user.name="$USER_NAME" \
    commit -q -m "Deploy Mnemo"
echo "Pushing ..."
if ! git push -q --force \
     "https://$USER_NAME:$HF_TOKEN@huggingface.co/spaces/$USER_NAME/$SPACE_NAME" main 2>/tmp/hfpush.err; then
  echo "ERROR: push failed." >&2; cat /tmp/hfpush.err >&2; exit 1
fi

cat <<DONE

Deployed: https://huggingface.co/spaces/$USER_NAME/$SPACE_NAME

Last step -- the Space is live but has no keys yet. Open
  https://huggingface.co/spaces/$USER_NAME/$SPACE_NAME/settings
and add these under "Variables and secrets" as SECRETS:
  NEBIUS_API_KEY
  TAVILY_API_KEY
The Space rebuilds on save. The badge should then read
"Token Factory + Tavily connected".
DONE
