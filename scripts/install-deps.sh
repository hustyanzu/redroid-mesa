#!/usr/bin/env bash
# Install host build dependencies (Fedora or Debian/Ubuntu CI).
# Usage: sudo bash scripts/install-deps.sh
set -euo pipefail

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
else
  echo "cannot detect OS" >&2
  exit 1
fi

case "${ID:-}:${ID_LIKE:-}" in
  *fedora*|*rhel*|*centos*)
    dnf install -y \
      meson ninja-build cmake git curl unzip patchelf \
      python3-mako python3-setuptools flex bison \
      clang clang-devel llvm llvm-devel \
      libclc libclc-devel libclc-spirv \
      glslang \
      spirv-llvm-translator spirv-llvm-translator-devel spirv-llvm-translator-tools \
      spirv-tools spirv-tools-devel spirv-tools-libs \
      libdrm-devel libudev-devel \
      libxml2-devel zlib-devel expat-devel \
      pkgconf-pkg-config
    ;;
  *debian*|*ubuntu*)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends \
      meson ninja-build cmake git curl unzip patchelf \
      python3-mako python3-setuptools flex bison \
      clang llvm-dev libclang-dev \
      libclc-dev \
      glslang-tools \
      libllvmspirvlib-dev llvm-spirv \
      libspirv-tools-dev spirv-tools \
      libdrm-dev libudev-dev \
      libxml2-dev zlib1g-dev libexpat1-dev \
      pkg-config ca-certificates
    ;;
  *)
    echo "unsupported distro: ${ID:-unknown}" >&2
    exit 1
    ;;
esac
