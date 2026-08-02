# redroid-mesa

Newer **Android Mesa (`iris`)** for **Redroid A13** host-GPU on **Intel iGPU**
(e.g. Arrow Lake `8086:7d67`) where stock Redroid’s Mesa is too old.

CI builds host `mesa_clc`, then cross-compiles **Android Mesa with
`gallium-drivers=iris` only** for **both `x86_64` and `x86`**, staged into
`/vendor/lib64` and `/vendor/lib`. AMD / other vendors are **not** in the image.

On non-`_64only` Redroid, host GPU (`egl=mesa`) loads Mesa for every ABI. Shipping
only a new 64-bit iris while leaving stock 32-bit Mesa in `/vendor/lib` is enough
to hang SurfaceFlinger / scrcpy on Arrow Lake — both ABIs must match.

## Variants

Base: Redroid **`13.0.0 (with 32-bit ABIs)`**. Non-pure images always include **houdini**.

### GHCR (CI publishes these)

| Tag | Contents |
|---|---|
| `a13` | Mesa only |
| `a13-houdini` | + houdini |
| `a13-houdini-supersu` | + houdini + **SuperSU switcher** (default Root OFF) |
| `a13-mindthegapps` | + houdini + MindTheGapps |
| `a13-mindthegapps-supersu` | + houdini + MindTheGapps + SuperSU switcher |
| `a13-magisk` | + houdini + Magisk (ayasa520 / redroid-script) |
| `a13-mindthegapps-magisk` / `latest` | + houdini + MindTheGapps + Magisk |

Magisk here is [ayasa520’s v30.7 fork](https://github.com/ayasa520/Magisk) (`com.topjohnwu.magisk`),
same `--setup-sbin` init as [redroid-script](https://github.com/ayasa520/redroid-script).
Stock topjohnwu Magisk dropped that flag and shows N/A on redroid.

Optional boot prop: `ro.setupwizard.mode=DISABLED` (skip GApps wizard).

### Local-only (not pushed to GHCR)

Still buildable with `./scripts/build.sh <id>` or `--all`:

| Tag | Contents |
|---|---|
| `a13-microg` | + houdini + MinMicroG |
| `a13-microg-magisk` | MinMicroG + ayasa520 Magisk |

`./scripts/build.sh --all` builds every local variant (Mesa once). CI does **not** push microg tags.

## SuperSU switcher (MuMu-like Root toggle)

Images with the `supersu` feature ship Chainfire **SuperSU 2.82 SR5** as an **off-PATH inventory** plus on-device toggles. Boot stays **Root OFF** (stock AOSP `/system/xbin/su` only) until you turn it on.

| Path | Role |
|---|---|
| `/system/etc/super-switcher/` | Inventory (`x64`/`x86` su, `Superuser.apk`) — **not** on `PATH` |
| `/system/bin/super-root-on` | Enable: install `su`/`daemonsu`, start daemon, `pm install` SuperSU (grant UI) |
| `/system/bin/super-root-off` | Disable: stop daemon, restore stock su, **uninstall** SuperSU package |
| `/data/local/super-switcher/` | Runtime state + one-time stock-su backup |

### Host (adb) helpers

```bash
# default serial 127.0.0.1:5555 — override with ADB='adb -s <serial>'
./scripts/super-switcher/root-on.sh
./scripts/super-switcher/root-off.sh
```

Or call directly:

```bash
adb -s 127.0.0.1:5555 root
adb -s 127.0.0.1:5555 shell /system/bin/super-root-on
adb -s 127.0.0.1:5555 shell /system/bin/super-root-off
```

Typical flow: **Root OFF** while playing games that detect root; **Root ON** when a helper needs interactive `su` (SuperSU may show a grant popup).

Do **not** mix Magisk and SuperSU features in one image.

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
      # Requires non-_64only base. On _64only these 32-bit ABIs cause exit 129.
      - ro.product.cpu.abilist=x86_64,x86,arm64-v8a,armeabi-v7a,armeabi
      - ro.product.cpu.abilist64=x86_64,arm64-v8a
      - ro.product.cpu.abilist32=x86,armeabi-v7a,armeabi
      - ro.dalvik.vm.isa.arm=x86
      - ro.dalvik.vm.isa.arm64=x86_64
      - ro.enable.native.bridge.exec=1
      - ro.enable.native.bridge.exec64=1
      - ro.dalvik.vm.native.bridge=libhoudini.so
```

For a local SuperSU image (guest GPU example):

```yaml
image: redroid-mesa:a13-houdini-supersu
# ...
command:
  - androidboot.redroid_gpu_mode=guest
  # ... same ABI / houdini props as above
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
chmod +x scripts/*.sh scripts/super-switcher/*.sh
./scripts/build.sh                  # pure a13
./scripts/build.sh a13-houdini-supersu
./scripts/build.sh a13-mindthegapps-supersu
./scripts/build.sh --mesa-only     # compile Mesa only
./scripts/build.sh --all           # all local variants (Mesa once)
SKIP_MESA_BUILD=1 ./scripts/build.sh a13-houdini-supersu
```
