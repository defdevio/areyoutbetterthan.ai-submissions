#!/usr/bin/env bash
# Frees ~30 GB on GitHub-hosted Ubuntu runners so large SWE-bench images fit.
set -euo pipefail
df -h / | tail -1
sudo rm -rf \
  /usr/share/dotnet \
  /usr/local/lib/android \
  /opt/ghc \
  /usr/local/.ghcup \
  /opt/hostedtoolcache/CodeQL \
  /usr/share/swift \
  /usr/local/share/powershell \
  /usr/local/share/chromium \
  /usr/local/lib/node_modules || true
docker image prune --all --force >/dev/null || true
df -h / | tail -1
