#!/usr/bin/env bash
# Assemble and push a Hugging Face Space from this repo.
#
# A Space repo needs Dockerfile and a front-matter README.md at ITS root, which
# is not how this repo is laid out -- and adding HF front-matter to our own
# README would render as a stray table on GitHub. So we assemble the Space
# layout in a temp dir and push that.
#
#   HF_TOKEN=hf_xxx ./scripts/deploy_space.sh <hf-username> [space-name]
#
# Pass --dry-run to assemble and print the layout without pushing.
set -euo pipefail

USER_NAME="${1:-}"
SPACE_NAME="${2:-mnemo}"
DRY_RUN="${DRY_RUN:-0}"
[ "${1:-}" = "--dry-run" ] && { DRY_RUN=1; USER_NAME="dry-run-user"; }
[ "${3:-}" = "--dry-run" ] && DRY_RUN=1

if [ -z "$USER_NAME" ]; then
  echo "usage: HF_TOKEN=hf_xxx $0 <hf-username> [space-name]" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -R "$ROOT/app" "$ROOT/web" "$ROOT/skills" "$STAGE/"
cp "$ROOT/requirements.txt" "$ROOT/LICENSE" "$STAGE/"
cp "$ROOT/deploy/Dockerfile.space" "$STAGE/Dockerfile"
cp "$ROOT/deploy/README-space.md" "$STAGE/README.md"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "Space layout assembled:"
(cd "$STAGE" && find . -type f -not -path './.git/*' | sort | sed 's/^/  /')

# The Space must declare the same port the container listens on.
APP_PORT="$(grep -E '^app_port:' "$STAGE/README.md" | awk '{print $2}')"
if ! grep -q "\${PORT:-$APP_PORT}" "$STAGE/Dockerfile"; then
  echo "ERROR: README app_port ($APP_PORT) does not match the Dockerfile CMD port." >&2
  exit 1
fi
echo "OK: app_port $APP_PORT matches the Dockerfile."

if [ "$DRY_RUN" = "1" ]; then
  echo "Dry run: nothing pushed."
  exit 0
fi

if [ -z "${HF_TOKEN:-}" ]; then
  echo "ERROR: set HF_TOKEN (Settings -> Access Tokens, needs write scope)." >&2
  exit 2
fi

cd "$STAGE"
git init -q -b main
git add -A
git -c user.email="noreply@huggingface.co" -c user.name="$USER_NAME" \
    commit -q -m "Deploy Mnemo"
echo "Pushing to https://huggingface.co/spaces/$USER_NAME/$SPACE_NAME ..."
git push -q --force \
  "https://$USER_NAME:$HF_TOKEN@huggingface.co/spaces/$USER_NAME/$SPACE_NAME" main
echo "Done: https://huggingface.co/spaces/$USER_NAME/$SPACE_NAME"
echo "Now add NEBIUS_API_KEY and TAVILY_API_KEY under Settings -> Variables and secrets."
