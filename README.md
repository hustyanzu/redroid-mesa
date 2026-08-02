# redroid-mesa

Newer **Android Mesa (`iris`)** for **Redroid A13** host-GPU on **Intel iGPU**
(e.g. Arrow Lake `8086:7d67`) where stock Redroid’s Mesa is too old.

CI (`publish.yml` → `build.sh`) builds the same thing as a local `--all`: host
`mesa_clc` tools, then cross-compiles **Android x86_64 Mesa with `gallium-drivers=iris` only**.
AMD (`radeonsi`) / other vendors are **not** in the image.

## Variants

Base: Redroid **`13.0.0_64only`**. Non-pure images always include **houdini**.
GApps picks **one of** microG / MindTheGapps; Magisk picks **one of** Kitsune / official.

| Tag | GApps | Magisk |
|---|---|---|
| `a13` | — | — |
| `a13-houdini` | — | — |
| `a13-microg` | MinMicroG | — |
| `a13-mindthegapps` | MindTheGapps | — |
| `a13-magiskdelta` | — | Kitsune (Magisk Delta / MagiskHide) |
| `a13-magisk` | — | Official Magisk (Zygisk; install Shamiko yourself) |
| `a13-microg-magiskdelta` | MinMicroG | Kitsune |
| `a13-microg-magisk` | MinMicroG | Official Magisk |
| `a13-mindthegapps-magiskdelta` | MindTheGapps | Kitsune |
| `a13-mindthegapps-magisk` / `latest` | MindTheGapps | Official Magisk |

Kitsune manager: `io.github.huskydg.magisk`. Official: `com.topjohnwu.magisk`.
Optional boot prop to skip GApps setup wizard: `ro.setupwizard.mode=DISABLED`.

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
      # optional DNS (default is 8.8.8.8 if unset)
      # - androidboot.redroid_net_ndns=2
      # - androidboot.redroid_net_dns1=223.5.5.5
      # - androidboot.redroid_net_dns2=223.6.6.6
      # optional system HTTP proxy (host must be reachable from the container; not 127.0.0.1)
      # - androidboot.redroid_net_proxy_type=static
      # - androidboot.redroid_net_proxy_host=172.18.0.1
      # - androidboot.redroid_net_proxy_port=7890
      # - androidboot.redroid_net_proxy_exclude_list=localhost,127.0.0.1
      # optional: skip GApps setup wizard
      # - ro.setupwizard.mode=DISABLED
      - ro.product.cpu.abilist=x86_64,arm64-v8a
      - ro.product.cpu.abilist64=x86_64,arm64-v8a
      - ro.dalvik.vm.isa.arm64=x86_64
      - ro.enable.native.bridge.exec=1
      - ro.dalvik.vm.native.bridge=libhoudini.so
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
./scripts/build.sh --mesa-only     # compile Mesa only
./scripts/build.sh --all           # all ten variants (Mesa compiled once)
SKIP_MESA_BUILD=1 ./scripts/build.sh --all
```
