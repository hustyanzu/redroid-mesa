#!/usr/bin/env bash
# CI-only: reclaim runner disk before large image builds.
set -euo pipefail

df -h || true

# Common large caches on the Ubuntu host (visible from privileged containers).
for d in \
  /usr/share/dotnet \
  /usr/local/lib/android \
  /opt/ghc \
  /opt/hostedtoolcache \
  /usr/local/share/powershell \
  /usr/share/swift
do
  if [[ -d "$d" ]]; then
    echo "removing $d"
    rm -rf "$d" || true
  fi
done

dnf clean all 2>/dev/null || true
rm -rf /var/cache/dnf/* 2>/dev/null || true

# Prefer workspace for buildah/podman scratch (same volume, easier to prune).
export TMPDIR="${TMPDIR:-${GITHUB_WORKSPACE:-/tmp}/.ci-tmp}"
mkdir -p "$TMPDIR"
echo "TMPDIR=$TMPDIR"

df -h || true
