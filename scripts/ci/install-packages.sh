#!/usr/bin/env bash
# CI-only: install Fedora build packages for GitHub Actions.
# End users: install packages yourself — see README.md (not this script).
set -euo pipefail

if [[ ! -r /etc/os-release ]]; then
  echo "cannot detect OS" >&2
  exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release

case "${ID:-}" in
  fedora) ;;
  *)
    echo "CI package script expects Fedora (got ${ID:-unknown})" >&2
    exit 1
    ;;
esac

dnf install -y \
  meson ninja-build cmake git curl unzip patchelf \
  python3 python3-mako python3-setuptools flex bison \
  clang clang-devel llvm llvm-devel \
  libclc libclc-devel libclc-spirv \
  glslang \
  spirv-llvm-translator spirv-llvm-translator-devel spirv-llvm-translator-tools \
  spirv-tools spirv-tools-devel spirv-tools-libs \
  libdrm-devel libudev-devel \
  libxml2-devel zlib-devel expat-devel \
  pkgconf-pkg-config \
  podman podman-docker
