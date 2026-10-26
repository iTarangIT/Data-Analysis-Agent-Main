#!/bin/bash
# Installed as /srv/analyst-agent/bin/receive and forced on the CI deploy key in root's
# authorized_keys, so that key can do nothing but this. The release tarball arrives on stdin and
# the commit sha as the SSH command; everything else is the release's own deploy/deploy.sh.
set -euo pipefail

sha=${SSH_ORIGINAL_COMMAND:-}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "usage: ssh <host> <full commit sha> < release.tar.gz" >&2; exit 2; }

exec 9>/srv/analyst-agent/.deploy.lock
flock -n 9 || { echo "another deploy is running" >&2; exit 1; }

incoming=/srv/analyst-agent/incoming/$sha
rm -rf "$incoming"
mkdir -p "$incoming"
tar -xz -C "$incoming"
bash "$incoming/deploy/deploy.sh" "$sha" "$incoming"
