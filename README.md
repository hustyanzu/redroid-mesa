# redroid-mesa

Newer **Android Mesa** for **Redroid A13** host-GPU — aimed at **Intel’s latest iGPUs**
(e.g. Arrow Lake `8086:7d67`) where the Mesa shipped in stock Redroid is too old.
Other relatively new GPUs that fail for the same reason can try these images too.

## Variants

| Tag | Contents |
|---|---|
| `a13` | Pure: Mesa only |
| `a13-houdini` | Mesa + **houdini** only |
| `a13-microg` | Mesa + **houdini** + MicroG |
| `a13-magiskdelta` | Mesa + **houdini** + Magisk Delta (Kitsune) |
| `a13-microg-magiskdelta` / `latest` | Mesa + **houdini** + microG + Magisk Delta (Kitsune) |

Magisk is **Kitsune Mask 31.0** (`io.github.huskydg.magisk`, MagiskHide) for **root + hide root** only.

Base image is Redroid **`13.0.0_64only`**.

## GHCR compose

```yaml
name: redroid-mesa

services:
  redroid:
    image: ghcr.io/<owner>/redroid-mesa:latest
    container_name: redroid-mesa
    restart: unless-stopped
    privileged: true
    stdin_open: true
    tty: true
    ports:
      - "5555:5555"
    volumes:
      - ./data:/data
      - /dev/binderfs:/dev/binderfs
      - /sys/kernel/debug:/sys/kernel/debug
    devices:
      - /dev/dri:/dev/dri
    command:
      - androidboot.redroid_width=720
      - androidboot.redroid_height=1280
      - androidboot.redroid_dpi=320
      - androidboot.redroid_fps=60
      - androidboot.redroid_gpu_mode=host
      - androidboot.redroid_gpu_node=/dev/dri/renderD128
      - androidboot.use_memfd=1
      - ro.product.cpu.abilist=x86_64,arm64-v8a
      - ro.product.cpu.abilist64=x86_64,arm64-v8a
      - ro.dalvik.vm.isa.arm64=x86_64
      - ro.enable.native.bridge.exec=1
      - ro.dalvik.vm.native.bridge=libhoudini.so

  scrcpy-web:
    image: shmayro/scrcpy-web:latest
    container_name: redroid-scrcpy-web
    restart: unless-stopped
    ports:
      - "8000:8000"
    depends_on:
      - redroid
    command:
      - sh
      - -c
      - |
        adb connect redroid:5555
        sleep 2
        adb devices
        npm start
```

## Host packages

Install build tools yourself (`build.sh` will not call `dnf`/`apt`).

### Fedora

```bash
sudo dnf install -y \
  meson ninja-build cmake git curl unzip patchelf \
  python3 python3-mako python3-pyyaml python3-setuptools flex bison \
  clang clang-devel llvm llvm-devel \
  libclc libclc-devel libclc-spirv \
  glslang \
  spirv-llvm-translator spirv-llvm-translator-devel spirv-llvm-translator-tools \
  spirv-tools spirv-tools-devel spirv-tools-libs \
  libdrm-devel libudev-devel \
  libxml2-devel zlib-devel expat-devel \
  pkgconf-pkg-config
```

### Ubuntu 24.04 (Noble) — LLVM 18

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  meson ninja-build cmake git curl unzip patchelf \
  python3-mako python3-yaml python3-setuptools flex bison \
  clang-18 llvm-18-dev libclang-18-dev \
  libclc-18 libclc-18-dev \
  glslang-tools \
  libllvmspirvlib-18-dev llvm-spirv-18 \
  libspirv-tools-dev spirv-tools \
  libdrm-dev libudev-dev \
  libxml2-dev zlib1g-dev libexpat1-dev \
  pkg-config ca-certificates
```

### Ubuntu 22.04 (Jammy) — LLVM 15

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  meson ninja-build cmake git curl unzip patchelf \
  python3-mako python3-yaml python3-setuptools flex bison \
  clang-15 llvm-15-dev libclang-15-dev \
  libclc-15 libclc-15-dev \
  glslang-tools \
  libllvmspirvlib-15-dev llvm-spirv-15 \
  libspirv-tools-dev spirv-tools \
  libdrm-dev libudev-dev \
  libxml2-dev zlib1g-dev libexpat1-dev \
  pkg-config ca-certificates
```

## Build locally

```bash
chmod +x scripts/*.sh
./scripts/build.sh                  # pure a13
./scripts/build.sh a13-microg
./scripts/build.sh --all            # all five variants (Mesa compiled once)
SKIP_MESA_BUILD=1 ./scripts/build.sh --all
```
