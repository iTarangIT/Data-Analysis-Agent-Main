#!/bin/bash
# Builds one release beside the live one, migrates, switches `current` to it and restarts the
# three units. If the new release is not healthy within two minutes, `current` goes back to the
# previous release. Run as root by receive.sh; every build step runs as the analyst user.
set -euo pipefail

sha=$1
src=$2
root=/srv/analyst-agent
shared=$root/shared
rel=$root/releases/${sha:0:7}
prev=$(readlink -f "$root/current" || true)
as_analyst() { runuser -u analyst -- env HOME=$root "$@"; }
log() { echo "==> $*"; }

if [ "$prev" = "$rel" ]; then
  log "${sha:0:7} is already live"
  rm -rf "$src"
  exit 0
fi

log "release ${sha:0:7}"
rm -rf "$rel"
mkdir -p "$rel"
mv "$src/analyst-agent-backend" "$rel/backend"
mv "$src/analyst-agent-frontend" "$rel/frontend"
rm -rf "$src"
ln -s "$shared/backend.env" "$rel/backend/.env"
ln -s "$shared/frontend.env" "$rel/frontend/.env.production.local"
chown -R analyst:analyst "$rel"

# A virtualenv per lock file, shared by every release built from it. The project itself is not
# installed into it: uvicorn and alembic import `app` from the release's own directory.
venv=$shared/venv-$(sha256sum "$rel/backend/requirements.lock" | cut -c1-12)
# Built where it will live, because pip writes that path into every script's shebang; the marker
# is what says a build finished.
if [ ! -f "$venv/.complete" ]; then
  log "new requirements.lock, building $(basename "$venv")"
  rm -rf "$venv"
  as_analyst python3.12 -m venv "$venv"
  # pip-compile on Windows pinned pywin32 without its platform marker; only mcp wants it, there.
  grep -v '^pywin32==' "$rel/backend/requirements.lock" > "$rel/backend/requirements.linux.txt"
  as_analyst "$venv/bin/pip" install -q --upgrade pip
  as_analyst "$venv/bin/pip" install -q -r "$rel/backend/requirements.linux.txt"
  touch "$venv/.complete"
fi
ln -s "$venv" "$rel/backend/.venv"

log "building the web app"
(cd "$rel/frontend" && as_analyst env npm_config_cache=$root/.npm NEXT_TELEMETRY_DISABLED=1 \
  bash -c 'npm ci --no-audit --no-fund --loglevel=error && npm run build' | tail -5)

log "migrating"
(cd "$rel/backend" && as_analyst .venv/bin/alembic upgrade head)

switch_to() {
  ln -sfn "$1" "$root/current.next"
  mv -T "$root/current.next" "$root/current"
  systemctl restart analyst-mcp analyst-api analyst-web
}

healthy() {
  for _ in $(seq 1 60); do
    if curl -sf -m 3 http://127.0.0.1:8000/health >/dev/null &&
      [ "$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3200/login)" = 200 ]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

log "switching"
switch_to "$rel"
if ! healthy; then
  journalctl -u analyst-mcp -u analyst-api -u analyst-web --since "-3min" --no-pager -o cat | tail -30
  if [ -n "$prev" ]; then
    log "unhealthy, rolling back to $(basename "$prev")"
    switch_to "$prev"
    healthy && log "rolled back" || log "the previous release is unhealthy too"
  fi
  exit 1
fi

log "pruning"
ls -1dt "$root"/releases/* | { grep -v -x -e "$rel" -e "$prev" || true; } | tail -n +4 | xargs -r rm -rf
for v in "$shared"/venv-*; do
  in_use=$(find "$root/releases" -maxdepth 3 -lname "$v" | head -1)
  [ -n "$in_use" ] || rm -rf "$v"
done

log "${sha:0:7} is live"
