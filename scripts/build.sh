#!/usr/bin/env bash
# Build redroid-mesa image: fetch → Mesa → stage vendor → docker image.
# Usage:
#   ./scripts/build.sh                 # pure a13
#   ./scripts/build.sh a13-microg
#   ./scripts/build.sh --mesa-only     # fetch + compile Mesa (no docker image)
#   ./scripts/build.sh --all           # all variants (Mesa once)
#   SKIP_MESA_BUILD=1 ./scripts/build.sh --all
# Host packages: install yourself (see README). CI uses scripts/ci/install-packages.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { printf '\n==== %s ====\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  else
    local q
    printf -v q '%q ' "$@"
    sg docker -c "docker $q"
  fi
}

load_variant() {
  local id="${1:?}"
  local f="$ROOT/variants/${id}/variant.env"
  [[ -f "$f" ]] || die "missing $f"
  # Prevent bleed from a previous variant when building --all
  unset VARIANT_ID BASE_IMAGE MESA_TAG ANDROID_API IMAGE_NAME IMAGE_TAG FEATURES MESA_VERSION
  set -a
  # shellcheck disable=SC1090
  source "$f"
  set +a
  VARIANT_ID="${VARIANT_ID:-$id}"
  BASE_IMAGE="${BASE_IMAGE:?}"
  MESA_TAG="${MESA_TAG:-mesa-26.1.5}"
  ANDROID_API="${ANDROID_API:-33}"
  IMAGE_NAME="${IMAGE_NAME:-redroid-mesa}"
  MESA_VERSION="${MESA_TAG#mesa-}"
  IMAGE_TAG="${IMAGE_TAG:-${VARIANT_ID}-${MESA_VERSION}}"
  FEATURES="${FEATURES:-}"
}

fetch_sources() {
  local tp="$ROOT/third_party"
  mkdir -p "$tp"
  cd "$tp"

  # Prefer existing NDK (symlink/copy or NDK_HOME); download only if missing.
  if [[ ! -d ndk/toolchains ]]; then
    if [[ -n "${NDK_HOME:-}" && -d "${NDK_HOME}/toolchains" ]]; then
      echo "Using NDK_HOME=${NDK_HOME}"
      ln -sfn "$NDK_HOME" ndk
    else
      echo "Downloading Android NDK r27c (resumable)..."
      rm -rf android-ndk-r27c
      # Keep partial ndk.zip so curl -C - can resume.
      curl -fL --retry 5 --retry-all-errors -C - -o ndk.zip \
        https://dl.google.com/android/repository/android-ndk-r27c-linux.zip
      unzip -q ndk.zip
      mv android-ndk-r27c ndk
      rm -f ndk.zip
    fi
  else
    echo "NDK: reuse $(readlink -f ndk 2>/dev/null || echo ndk)"
  fi
  test -x "ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android${ANDROID_API}-clang"

  local cur=""
  [[ -d mesa/.git ]] && cur="$(git -C mesa describe --tags --exact-match 2>/dev/null || true)"
  if [[ ! -d mesa/.git ]] || [[ "$cur" != "$MESA_TAG" ]]; then
    echo "Cloning Mesa ${MESA_TAG}..."
    # Only remove a real clone dir, not a symlink to an existing tree.
    if [[ -L mesa ]]; then
      die "third_party/mesa symlink points to wrong tag ($cur != $MESA_TAG); fix or remove it"
    fi
    rm -rf mesa
    git clone --depth 1 --branch "$MESA_TAG" \
      https://gitlab.freedesktop.org/mesa/mesa.git mesa
  else
    echo "Mesa: reuse $(readlink -f mesa 2>/dev/null || echo mesa) ($cur)"
  fi
  cd mesa
  for p in "$ROOT"/patches/*.patch; do
    [[ -f "$p" ]] || continue
    if git apply --reverse --check "$p" 2>/dev/null; then
      echo "patch $(basename "$p"): already applied"
    elif git apply --check "$p" 2>/dev/null; then
      git apply "$p"
      echo "patch $(basename "$p"): applied"
    else
      echo "patch $(basename "$p"): skip"
    fi
  done
  echo "Mesa: $(git describe --tags --always)"
  cd "$ROOT"
}

build_mesa_clc() {
  local mesa="$ROOT/third_party/mesa"
  local out="$ROOT/out/mesa-compiler"
  local build="$ROOT/out/build-compiler"
  rm -rf "$build"
  mkdir -p "$ROOT/out"
  meson setup "$build" "$mesa" \
    -Dprefix="$out" \
    -Dbuildtype=release \
    -Dplatforms= \
    -Dgallium-drivers= \
    -Dvulkan-drivers= \
    -Dmesa-clc=enabled \
    -Dinstall-mesa-clc=true \
    -Dllvm=enabled \
    -Dshared-llvm=enabled \
    -Dlibunwind=disabled \
    -Dmicrosoft-clc=disabled \
    -Dvalgrind=disabled \
    -Dlmsensors=disabled \
    -Dbuild-tests=false
  ninja -C "$build" install
  export PATH="$out/bin:$PATH"
  command -v mesa_clc >/dev/null
  command -v vtn_bindgen2 >/dev/null
}

build_android_mesa() {
  local mesa="$ROOT/third_party/mesa"
  local ndk="$ROOT/third_party/ndk"
  local tc="$ndk/toolchains/llvm/prebuilt/linux-x86_64"
  local cross="$ROOT/out/android-x86_64.cross"
  local build="$ROOT/out/build-android-x86_64"
  local prefix="$ROOT/out/android-x86_64"
  export PATH="${ROOT}/out/mesa-compiler/bin:${PATH:-}"

  cat > "$cross" <<EOF
[binaries]
ar = '$tc/bin/llvm-ar'
c = '$tc/bin/x86_64-linux-android${ANDROID_API}-clang'
cpp = ['$tc/bin/x86_64-linux-android${ANDROID_API}-clang++', '-fno-exceptions', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-static-libstdc++']
c_ld = 'lld'
cpp_ld = 'lld'
strip = '$tc/bin/llvm-strip'
pkg-config = 'false'

[host_machine]
system = 'android'
cpu_family = 'x86_64'
cpu = 'x86_64'
endian = 'little'

[properties]
needs_exe_wrapper = true
EOF

  rm -rf "$build" "$prefix"
  mkdir -p "$ROOT/out"
  meson setup "$build" "$mesa" \
    --cross-file "$cross" \
    --prefix="$prefix" \
    -Dbuildtype=release \
    -Dplatforms=android \
    -Dplatform-sdk-version="${ANDROID_API}" \
    -Dandroid-stub=true \
    -Dandroid-libbacktrace=disabled \
    -Dgallium-drivers=iris \
    -Dvulkan-drivers= \
    -Degl=enabled \
    -Dgbm=enabled \
    -Dglx=disabled \
    -Dgles1=enabled \
    -Dgles2=enabled \
    -Dmesa-clc=system \
    -Dllvm=disabled \
    -Dallow-fallback-for=libdrm \
    -Dlibunwind=disabled \
    -Dmicrosoft-clc=disabled \
    -Dvalgrind=disabled \
    -Dlmsensors=disabled \
    -Dbuild-tests=false
  ninja -C "$build"
  DESTDIR= ninja -C "$build" install
  # Drop meson/ninja trees; keep install prefix for stage_vendor.
  rm -rf "$build" "$ROOT/out/build-compiler"
}

stage_vendor() {
  local src="$ROOT/out/android-x86_64/lib"
  local dst="$ROOT/out/vendor-mesa"
  local baked_gbm="$ROOT/out/android-x86_64/lib/gbm"

  [[ -f "$src/libgallium_dri.so" ]] || die "missing Android Mesa build"
  command -v patchelf >/dev/null || die "patchelf required"

  rm -rf "$dst"
  mkdir -p "$dst/vendor/lib64/egl" "$dst/vendor/lib64/dri" "$dst/vendor/lib64/gbm"

  install -m 0755 "$src/libEGL.so"       "$dst/vendor/lib64/egl/libEGL_mesa.so"
  install -m 0755 "$src/libGLESv1_CM.so" "$dst/vendor/lib64/egl/libGLESv1_CM_mesa.so"
  install -m 0755 "$src/libGLESv2.so"    "$dst/vendor/lib64/egl/libGLESv2_mesa.so"
  install -m 0755 "$src/libgallium_dri.so" "$dst/vendor/lib64/dri/libgallium_dri.so"
  ln -sfn libgallium_dri.so "$dst/vendor/lib64/dri/iris_dri.so"
  install -m 0755 "$src/libgallium_dri.so" "$dst/vendor/lib64/libgallium_dri.so"
  install -m 0755 "$src/libdrm.so"   "$dst/vendor/lib64/libdrm.so"
  install -m 0755 "$src/libexpat.so" "$dst/vendor/lib64/libexpat.so"
  install -m 0755 "$src/libgbm_mesa.so" "$dst/vendor/lib64/libgbm.so.1"
  patchelf --set-soname libgbm.so.1 "$dst/vendor/lib64/libgbm.so.1"
  install -m 0755 "$src/gbm/dri_gbm.so" "$dst/vendor/lib64/gbm/dri_gbm.so"

  python3 - "$dst/vendor/lib64/libgbm.so.1" "$baked_gbm" <<'PY'
import sys
from pathlib import Path
path, baked = Path(sys.argv[1]), sys.argv[2].encode()
new = b"/vendor/lib64/gbm"
data = bytearray(path.read_bytes())

def patch(blob, old, new):
    if old not in blob:
        return False
    if len(new) > len(old):
        raise SystemExit("replacement too long")
    blob[:] = blob.replace(old, new + b"\0" * (len(old) - len(new)))
    return True

if not patch(data, baked, new):
    needle = b"/lib/gbm"
    idx = data.find(needle)
    if idx < 0:
        raise SystemExit("GBM path not found")
    start = idx
    while start > 0 and data[start - 1] != 0:
        start -= 1
    old = bytes(data[start:idx + len(needle)])
    if not patch(data, old, new):
        raise SystemExit(f"failed to patch {old!r}")
path.write_bytes(data)
print("patched GBM_BACKENDS_PATH -> /vendor/lib64/gbm")
PY

  grep -a -q '7d67' "$dst/vendor/lib64/dri/libgallium_dri.so" || die "0x7d67 missing"
  echo "staged $dst (PCI 0x7d67 OK)"
}

docker_image() {
  local ctx="$ROOT/out/docker-context/${VARIANT_ID}"
  local features="${FEATURES:-}"
  local f
  rm -rf "$ctx"
  mkdir -p "$ctx/root"
  cp -a "$ROOT/out/vendor-mesa/vendor" "$ctx/root/vendor"
  cp "$ROOT/docker/Dockerfile" "$ctx/Dockerfile"
  cp "$ROOT/docker/.dockerignore" "$ctx/.dockerignore"

  if [[ -n "$features" ]]; then
    log "stage extras ($features)"
    python3 "$ROOT/scripts/stage_extras.py" --features "$features"
    IFS=',' read -r -a feat_arr <<< "$features"
    for f in "${feat_arr[@]}"; do
      f="$(echo "$f" | tr -d '[:space:]')"
      [[ -n "$f" ]] || continue
      [[ -d "$ROOT/out/extras/$f" ]] || die "missing out/extras/$f"
      cp -a "$ROOT/out/extras/$f"/. "$ctx/root/"
    done
  fi

  local tags=(-t "${IMAGE_NAME}:${IMAGE_TAG}" -t "${IMAGE_NAME}:${VARIANT_ID}")
  if [[ "$VARIANT_ID" == "a13-mindthegapps-magisk" ]]; then
    tags+=(-t "${IMAGE_NAME}:latest")
  fi

  docker_cmd build \
    --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
    --label "org.opencontainers.image.title=redroid-mesa" \
    --label "org.opencontainers.image.description=Redroid A13 + Mesa ${MESA_VERSION} (${VARIANT_ID})" \
    --label "org.opencontainers.image.source=${IMAGE_SOURCE:-https://github.com/${GITHUB_REPOSITORY:-}}" \
    --label "org.opencontainers.image.version=${IMAGE_TAG}" \
    --label "org.opencontainers.image.revision=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)" \
    --label "io.redroid.mesa.variant=${VARIANT_ID}" \
    --label "io.redroid.mesa.version=${MESA_VERSION}" \
    --label "io.redroid.mesa.features=${features}" \
    --label "io.redroid.base.image=${BASE_IMAGE}" \
    "${tags[@]}" \
    "$ctx"

  rm -rf "$ctx"
  echo "Local tags: ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${VARIANT_ID}"
}

build_one() {
  local id="$1"
  load_variant "$id"
  log "stage vendor ($VARIANT_ID)"
  stage_vendor
  log "docker image ($VARIANT_ID)"
  docker_image
}

# --- main ---
ALL_VARIANTS=(
  a13
  a13-houdini
  a13-microg
  a13-mindthegapps
  a13-magiskdelta
  a13-magisk
  a13-microg-magiskdelta
  a13-microg-magisk
  a13-mindthegapps-magiskdelta
  a13-mindthegapps-magisk
)

ensure_mesa() {
  if [[ "${SKIP_MESA_BUILD:-0}" == "1" ]]; then
    log "reuse existing out/android-x86_64"
    [[ -f "$ROOT/out/android-x86_64/lib/libgallium_dri.so" ]] || die "no Mesa build present"
    return
  fi
  # Mesa is shared — load any variant for MESA_TAG / ANDROID_API
  load_variant a13
  log "fetch"
  fetch_sources
  log "mesa_clc"
  build_mesa_clc
  log "android mesa"
  build_android_mesa
  # Host CLC tools not needed after Android Mesa is installed.
  rm -rf "$ROOT/out/mesa-compiler" "$ROOT/out/build-compiler"
}

if [[ "${1:-}" == "--mesa-only" ]]; then
  ensure_mesa
  log "DONE (mesa only)"
  exit 0
fi

if [[ "${1:-}" == "--all" ]]; then
  ensure_mesa
  for id in "${ALL_VARIANTS[@]}"; do
    build_one "$id"
  done
  log "DONE (all variants)"
  exit 0
fi

VARIANT_ID="${1:-a13}"
load_variant "$VARIANT_ID"

if [[ "${SKIP_MESA_BUILD:-0}" == "1" ]]; then
  log "reuse existing out/android-x86_64"
  [[ -f "$ROOT/out/android-x86_64/lib/libgallium_dri.so" ]] || die "no Mesa build present"
else
  ensure_mesa
fi

build_one "$VARIANT_ID"
log "DONE"
