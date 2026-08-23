# redroid-mesa

Layered images on top of the **[official redroid Docker image](https://github.com/remote-android/redroid-doc)**
(`redroid/redroid`) — **no full AOSP / redroid source build**. We only rebuild a
newer **Android Mesa 26.1.5+ (`iris`)** and stage optional system overlays (houdini,
GApps, Magisk, SuperSU).

Target: **Redroid A13** host-GPU on **Intel iGPU** (e.g. Arrow Lake `8086:7d67`)
where stock Redroid’s Mesa is too old.

CI builds host `mesa_clc`, then cross-compiles **Android Mesa with
`gallium-drivers=iris` only** for **both `x86_64` and `x86`**, staged into
`/vendor/lib64` and `/vendor/lib`. AMD / other vendors are **not** in the image.

## Variants

Base: Redroid **`13.0.0`**.

`image: ghcr.io/hustyanzu/redroid-mesa:<tag>`

| Tag | Contents |
|---|---|
| `a13` / `latest` | Mesa only (pure) |
| `a13-houdini` | + houdini |
| `a13-supersu` | + houdini + **SuperSU** (default Root OFF) |
| `a13-mindthegapps` | + houdini + MindTheGapps |
| `a13-mindthegapps-supersu` | + houdini + MindTheGapps + SuperSU + FLAG_SECURE ignore |
| `a13-magisk` | + houdini + Magisk (ayasa520 / redroid-script) |
| `a13-mindthegapps-magisk` | + houdini + MindTheGapps + Magisk |

Magisk here is [ayasa520’s v30.7 fork](https://github.com/ayasa520/Magisk) (`com.topjohnwu.magisk`),
same `--setup-sbin` init as [redroid-script](https://github.com/ayasa520/redroid-script).
Stock topjohnwu Magisk dropped that flag and shows N/A on redroid.

MindTheGapps is [MindTheGapps 13.0.0 x86_64](https://github.com/MindTheGapps/13.0.0-x86_64/releases/tag/MindTheGapps-13.0.0-x86_64-20231025_201203).

SuperSU is Chainfire [2.82 SR5](https://download.chainfire.eu/1220/SuperSU/),
vendored at `vendor/supersu/`.

### FLAG_SECURE ignore (`flagsecure`)

`a13-mindthegapps-supersu` patches `/system/framework/services.jar` so
`isSecureLocked()` always returns false (scrcpy / screencap no longer black on
secure windows). Only that method is patched — not `isScreenCaptureAllowed` /
`getScreenCaptureDisabled`.

Build needs a booted redroid for `dex2oat` (auto-detects `redroid-mesa-1`, or set
`FLAGSECURE_DEX_CONTAINER` / `FLAGSECURE_ADB`). Tooling comes from
[FlagSecurePatcher](https://github.com/j-hc/FlagSecurePatcher) r17.

### VpnService / `/dev/tun`

All images ship `system/etc/init/tun-dev.rc`, which creates `/dev/tun` on boot.
Without it, apps using `VpnService` (e.g. UU) fail with `Cannot allocate TUN`.
The tunnel lives in the container network namespace — it does not change host routing.

`./scripts/build.sh --all` builds every variant above (Mesa once).

### SuperSU (Recommended for temporary root access)

Images with the `supersu` feature ship SuperSU as an **off-PATH inventory** plus on-device toggles.
Boot stays **Root OFF** (stock AOSP `/system/xbin/su` only) until you turn it on.

```bash
adb -s 127.0.0.1:5555 root
adb -s 127.0.0.1:5555 shell /system/bin/super-root-on
adb -s 127.0.0.1:5555 shell /system/bin/super-root-off
```

Typical flow: **Root OFF** while playing games that detect root; **Root ON** when needs interactive `su`.
Changes take effect immediately—no restart required.

| Path | Role |
|---|---|
| `/system/bin/super-root-on` | Enable: install `su`/`daemonsu`, start daemon, `pm install` SuperSU (grant UI) |
| `/system/bin/super-root-off` | Disable: stop daemon, restore stock su, **uninstall** SuperSU package |
| `/system/etc/super-switcher/` | Inventory (`x64`/`x86` su, `Superuser.apk`) |
| `/data/local/super-switcher/` | Runtime state + one-time stock-su backup |

*Magisk itself works properly, but many of my attempts to hide Magisk and root access have failed. You can give it a try.*

## compose

```yaml
name: redroid-mesa

services:
  redroid:
    image: ghcr.io/hustyanzu/redroid-mesa:latest
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
      # optional display change
      # - androidboot.redroid_width=720
      # - androidboot.redroid_height=1280
      # - androidboot.redroid_dpi=320
      # - androidboot.redroid_fps=60
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
      - ro.setupwizard.mode=DISABLED
      # houdini variants also need ABI / native-bridge props — see compose/docker-compose.houdini.yml
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
./scripts/build.sh a13-supersu
./scripts/build.sh a13-mindthegapps-supersu
./scripts/build.sh --mesa-only     # compile Mesa only
./scripts/build.sh --all           # all variants (Mesa once)
SKIP_MESA_BUILD=1 ./scripts/build.sh a13-supersu
```
