#!/usr/bin/env python3
"""Stage system overlays → out/extras/<name>/

Features: houdini, mindthegapps, magisk (ayasa520/redroid), supersu (switchable).
Fetch caches live under third_party/downloads/; SuperSU is vendored at
third_party/supersu/ (Chainfire CDN is flaky / may vanish).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DL = ROOT / "third_party" / "downloads"
EXTRAS = ROOT / "out" / "extras"

HOUDINI_URL = (
    "https://github.com/rote66/vendor_intel_proprietary_houdini/archive/"
    "debc3dc91cf12b5c5b8a1c546a5b0b7bf7f838a8.zip"
)
HOUDINI_MD5 = "cb7ffac26d47ec7c89df43818e126b47"
HOUDINI_HACK_URL = (
    "https://github.com/rote66/redroid_libhoudini_hack/archive/"
    "a2194c5e294cbbfdfe87e51eb9eddb4c3621d8c3.zip"
)
HOUDINI_HACK_MD5 = "8f71a58f3e54eca879a2f7de64dbed58"

# Same source as ayasa520/redroid-script: Magisk v30.7 fork that keeps
# --auto-selinux / --setup-sbin (stock topjohnwu removed both → manager N/A on redroid).
# Package: com.topjohnwu.magisk (different signing key than stock).
MAGISK_URL = (
    "https://github.com/ayasa520/Magisk/releases/download/v30.7/Magisk-v30.7.apk"
)
MAGISK_MD5 = "0a31050fdcfaa15f47c9dd1eb8d04fc8"

# SuperSU 2.82 SR5 (Chainfire) — vendored; original:
# https://download.chainfire.eu/1220/SuperSU/SR5-SuperSU-v2.82-SR5-20171001224502.zip
SUPERSU_MD5 = "f20d6d46b454cb74470977cb445eb8e4"
SUPERSU_ZIP = ROOT / "third_party" / "supersu" / "SR5-SuperSU-v2.82-SR5.zip"

MINDTHEGAPPS_URL = (
    "https://github.com/MindTheGapps/13.0.0-x86_64/releases/download/"
    "MindTheGapps-13.0.0-x86_64-20231025_201203/"
    "MindTheGapps-13.0.0-x86_64-20231025_201203.zip"
)
MINDTHEGAPPS_MD5 = "8e08d656acfbb86bbc7b5f9608468ba7"

ANDROID_VER = "13.0.0"

# Toybox patch has no GNU -N/-r; use -i. Fallback appends arm/arm64 paths if hunks fail.
HOUDINI_PATCH_LD_SH = r"""#!/system/bin/sh
# After apexd generates /linkerconfig, allow houdini to dlopen /system/lib64/arm64/*.
set -e

ensure_line() {
  # ensure_line <file> <exact-line>
  f="$1"
  line="$2"
  grep -Fqx "$line" "$f" 2>/dev/null && return 0
  printf '%s\n' "$line" >> "$f"
}

ensure_houdini_paths() {
  f="$1"
  [ -f "$f" ] || return 0
  # permitted + search for default namespace (libtcb.so lives under arm64/)
  for p in \
    'namespace.default.permitted.paths += /system/${LIB}' \
    'namespace.default.permitted.paths += /system/${LIB}/arm' \
    'namespace.default.permitted.paths += /system/${LIB}/arm/nb' \
    'namespace.default.permitted.paths += /system/${LIB}/arm64' \
    'namespace.default.permitted.paths += /system/${LIB}/arm64/nb' \
    'namespace.default.permitted.paths += /apex/com.android.art/${LIB}' \
    'namespace.default.search.paths += /system/${LIB}/arm' \
    'namespace.default.search.paths += /system/${LIB}/arm/nb' \
    'namespace.default.search.paths += /system/${LIB}/arm64' \
    'namespace.default.search.paths += /system/${LIB}/arm64/nb'
  do
    ensure_line "$f" "$p"
  done
}

apply_one() {
  cfg="$1"
  patchf="$2"
  [ -f "$cfg" ] || return 0
  [ -f "$patchf" ] || { ensure_houdini_paths "$cfg"; return 0; }
  # Toybox patch: -i PATCH FILE (no -N/-r)
  if /system/bin/patch -i "$patchf" "$cfg"; then
    return 0
  fi
  ensure_houdini_paths "$cfg"
}

apply_one /linkerconfig/ld.config.txt /system/etc/ld_config.patch
apply_one /linkerconfig/com.android.media.swcodec/ld.config.txt /system/etc/ld_config_swcodec.patch
exit 0
"""

HOUDINI_RC = r"""
on early-init
    mount binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc

on property:ro.enable.native.bridge.exec=1
    copy /system/etc/binfmt_misc/arm_exe /proc/sys/fs/binfmt_misc/register
    copy /system/etc/binfmt_misc/arm_dyn /proc/sys/fs/binfmt_misc/register

on property:ro.enable.native.bridge.exec64=1
    copy /system/etc/binfmt_misc/arm64_exe /proc/sys/fs/binfmt_misc/register
    copy /system/etc/binfmt_misc/arm64_dyn /proc/sys/fs/binfmt_misc/register

# linkerconfig is generated here; must patch after apexd (tmpfs /linkerconfig).
# A13 apexd sets apexd.status=ready (not "activated").
on property:apexd.status=ready
    exec u:r:su:s0 root root -- /system/bin/sh /system/etc/houdini_patch_ld.sh

on property:sys.boot_completed=1
    exec -- /system/bin/sh -c "echo ':arm_exe:M::\\x7f\\x45\\x4c\\x46\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x28::/system/bin/houdini:P' >> /proc/sys/fs/binfmt_misc/register"
    exec -- /system/bin/sh -c "echo ':arm_dyn:M::\\x7f\\x45\\x4c\\x46\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x03\\x00\\x28::/system/bin/houdini:P' >> /proc/sys/fs/binfmt_misc/register"
    exec -- /system/bin/sh -c "echo ':arm64_exe:M::\\x7f\\x45\\x4c\\x46\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\xb7::/system/bin/houdini64:P' >> /proc/sys/fs/binfmt_misc/register"
    exec -- /system/bin/sh -c "echo ':arm64_dyn:M::\\x7f\\x45\\x4c\\x46\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x03\\x00\\xb7::/system/bin/houdini64:P' >> /proc/sys/fs/binfmt_misc/register"
"""

# Same init pattern as ayasa520/redroid-script (bootanim.rc snippet), as a dedicated magisk.rc.
# Requires a Magisk build that still has --auto-selinux / --setup-sbin (ayasa520).
MAGISK_RC_TEMPLATE = """
on post-fs-data
    start logd
    exec u:r:su:s0 root root -- /system/etc/init/magisk/magiskpolicy --live --magisk
    exec u:r:magisk:s0 root root -- /system/etc/init/magisk/magiskpolicy --live --magisk
    exec u:r:update_engine:s0 root root -- /system/etc/init/magisk/magiskpolicy --live --magisk
    exec u:r:su:s0 root root -- /system/etc/init/magisk/magisk64 --auto-selinux --setup-sbin /system/etc/init/magisk /sbin
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --post-fs-data
on nonencrypted
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --service
on property:vold.decrypt=trigger_restart_framework
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --service
on property:sys.boot_completed=1
    mkdir /data/adb/magisk 755
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --boot-complete
    exec -- /system/bin/sh -c "if [ ! -e /data/data/{package} ] ; then pm install /system/etc/init/magisk/magisk.apk ; fi"

on property:init.svc.zygote=restarting
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --zygote-restart

on property:init.svc.zygote=stopped
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --zygote-restart
"""

def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_download(url: str, dest: Path, expect_md5: str) -> Path:
    DL.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and md5_file(dest) == expect_md5:
        print(f"cache hit {dest.name}")
        return dest
    print(f"download {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.unlink(missing_ok=True)
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "5",
            "--retry-all-errors",
            "-C",
            "-",
            "-o",
            str(tmp),
            url,
        ],
        check=True,
    )
    got = md5_file(tmp)
    if got != expect_md5:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"md5 mismatch for {dest.name}: {got} != {expect_md5}")
    tmp.replace(dest)
    return dest


def unzip_to(archive: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)


def merge_tree(src: Path, dst: Path) -> None:
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            s = Path(root) / name
            d = target_dir / name
            shutil.copy2(s, d)
            mode = s.stat().st_mode
            os.chmod(d, mode)


def stage_houdini(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    z = ensure_download(HOUDINI_URL, DL / "libhoudini.zip", HOUDINI_MD5)
    with tempfile.TemporaryDirectory(prefix="houdini-") as td:
        td_path = Path(td)
        unzip_to(z, td_path / "u")
        roots = list((td_path / "u").glob("vendor_intel_proprietary_houdini-*/prebuilts"))
        if not roots:
            raise SystemExit("houdini prebuilts not found")
        merge_tree(roots[0], out / "system")

    hz = ensure_download(HOUDINI_HACK_URL, DL / "libhoudini_hack.zip", HOUDINI_HACK_MD5)
    with tempfile.TemporaryDirectory(prefix="houdini-hack-") as td:
        td_path = Path(td)
        unzip_to(hz, td_path / "u")
        matches = list((td_path / "u").glob(f"redroid_libhoudini_hack-*/{ANDROID_VER}"))
        if not matches:
            raise SystemExit(f"houdini hack for {ANDROID_VER} not found")
        etc = matches[0] / "etc"
        dest_etc = out / "system" / "etc"
        dest_etc.mkdir(parents=True, exist_ok=True)
        for name in ("ld_config.patch", "ld_config_swcodec.patch"):
            src = etc / name
            if src.is_file():
                shutil.copy2(src, dest_etc / name)

    script = out / "system/etc/houdini_patch_ld.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(HOUDINI_PATCH_LD_SH.lstrip("\n"))
    os.chmod(script, 0o755)

    rc = out / "system/etc/init/houdini.rc"
    rc.parent.mkdir(parents=True, exist_ok=True)
    rc.write_text(HOUDINI_RC.lstrip("\n"))
    os.chmod(rc, 0o644)
    bad = out / "system/etc/init/hw/init.rc"
    if bad.exists():
        bad.unlink()
    print(f"staged houdini → {out}")


def stage_magisk_apk(
    out: Path,
    *,
    url: str,
    md5: str,
    cache_name: str,
    label: str,
    package: str,
) -> None:
    """Extract Magisk APK libs + write magisk.rc (redroid-script style setup-sbin)."""
    if out.exists():
        shutil.rmtree(out)
    magisk_dir = out / "system/etc/init/magisk"
    magisk_dir.mkdir(parents=True)
    (out / "sbin").mkdir(parents=True, exist_ok=True)

    apk = ensure_download(url, DL / cache_name, md5)
    with tempfile.TemporaryDirectory(prefix="magisk-") as td:
        td_path = Path(td)
        unzip_to(apk, td_path / "apk")
        lib_dir = td_path / "apk" / "lib" / "x86_64"
        if not lib_dir.is_dir():
            raise SystemExit(f"{label}: magisk x86_64 libs missing")
        for so in lib_dir.glob("lib*.so"):
            m = re.search(r"lib(.*)\.so", so.name)
            if not m:
                continue
            dest = magisk_dir / m.group(1)
            shutil.copyfile(so, dest)
            os.chmod(dest, 0o755)
        magisk64 = magisk_dir / "magisk64"
        magisk = magisk_dir / "magisk"
        if magisk64.is_file() and not magisk.is_file():
            shutil.copyfile(magisk64, magisk)
            os.chmod(magisk, 0o755)
        if magisk.is_file() and not magisk64.is_file():
            shutil.copyfile(magisk, magisk64)
            os.chmod(magisk64, 0o755)
        if not magisk64.is_file() and not magisk.is_file():
            raise SystemExit(f"{label}: magisk/magisk64 binary missing after extract")
        # Binary must support redroid init flags (Android ELF — strings scan only).
        probe = magisk64 if magisk64.is_file() else magisk
        if b"--setup-sbin" not in probe.read_bytes():
            raise SystemExit(
                f"{label}: APK magisk binary lacks --setup-sbin "
                "(need ayasa520 Magisk, not stock topjohnwu)"
            )
        stub = td_path / "apk" / "assets" / "stub.apk"
        if stub.is_file():
            shutil.copyfile(stub, magisk_dir / "stub.apk")

    shutil.copyfile(apk, magisk_dir / "magisk.apk")
    rc = out / "system/etc/init/magisk.rc"
    rc.write_text(MAGISK_RC_TEMPLATE.format(package=package).lstrip("\n"))
    os.chmod(rc, 0o644)
    print(f"staged {label} → {out} (package={package})")


def stage_magisk(out: Path) -> None:
    stage_magisk_apk(
        out,
        url=MAGISK_URL,
        md5=MAGISK_MD5,
        cache_name="magisk-ayasa520.apk",
        label="magisk",
        package="com.topjohnwu.magisk",
    )


def stage_mindthegapps(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    z = ensure_download(MINDTHEGAPPS_URL, DL / "MindTheGapps-13.0.0-x86_64.zip", MINDTHEGAPPS_MD5)
    with tempfile.TemporaryDirectory(prefix="mtg-") as td:
        td_path = Path(td)
        unzip_to(z, td_path / "u")
        # Zip layout: system/ at root, or nested under one directory.
        src_system = td_path / "u" / "system"
        if not src_system.is_dir():
            found = list((td_path / "u").glob("*/system"))
            if not found:
                raise SystemExit("MindTheGapps system/ missing")
            src_system = found[0]
            base = src_system.parent
        else:
            base = td_path / "u"

        merge_tree(src_system, out / "system")
        # Some builds also ship product/ alongside system/
        src_product = base / "product"
        if src_product.is_dir():
            merge_tree(src_product, out / "system" / "product")

    print(f"staged mindthegapps → {out}")


def stage_supersu(out: Path) -> None:
    """Stage SuperSU inventory + on-device toggle scripts. Default Root OFF (no boot daemon)."""
    if out.exists():
        shutil.rmtree(out)
    inv = out / "system/etc/super-switcher"
    inv.mkdir(parents=True)

    if not SUPERSU_ZIP.is_file():
        raise SystemExit(f"missing vendored SuperSU: {SUPERSU_ZIP}")
    got = md5_file(SUPERSU_ZIP)
    if got != SUPERSU_MD5:
        raise SystemExit(f"md5 mismatch for {SUPERSU_ZIP.name}: {got} != {SUPERSU_MD5}")
    z = SUPERSU_ZIP
    print(f"using vendored {SUPERSU_ZIP.relative_to(ROOT)}")

    with tempfile.TemporaryDirectory(prefix="supersu-") as td:
        td_path = Path(td)
        unzip_to(z, td_path / "u")
        root = td_path / "u"
        # Zip may extract flat or under one top dir
        if not (root / "x64").is_dir():
            found = list(root.glob("*/x64"))
            if not found:
                raise SystemExit("SuperSU x64/ missing")
            root = found[0].parent

        for arch in ("x64", "x86"):
            src = root / arch
            if not src.is_dir():
                raise SystemExit(f"SuperSU {arch}/ missing")
            dest = inv / arch
            dest.mkdir(parents=True)
            su_name = "su.pie" if arch == "x86" and (src / "su.pie").is_file() else "su"
            shutil.copy2(src / su_name, dest / "su")
            shutil.copy2(src / "libsupol.so", dest / "libsupol.so")
            os.chmod(dest / "su", 0o755)

        common = root / "common"
        dest_c = inv / "common"
        dest_c.mkdir(parents=True)
        shutil.copy2(common / "Superuser.apk", dest_c / "Superuser.apk")
        shutil.copy2(common / "install-recovery.sh", dest_c / "install-recovery.sh")
        os.chmod(dest_c / "install-recovery.sh", 0o755)

    scripts_src = ROOT / "scripts/super-switcher/on-device"
    bindir = out / "system/bin"
    bindir.mkdir(parents=True, exist_ok=True)
    for name in ("super-root-on", "super-root-off"):
        src = scripts_src / name
        if not src.is_file():
            raise SystemExit(f"missing {src}")
        dest = bindir / name
        shutil.copy2(src, dest)
        os.chmod(dest, 0o755)

    print(f"staged supersu → {out} (inventory under /system/etc/super-switcher)")


FEATURE_CHOICES = ["houdini", "mindthegapps", "magisk", "supersu"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "features",
        nargs="*",
        choices=FEATURE_CHOICES,
        help="features to stage",
    )
    p.add_argument("--features", dest="features_csv", default="")
    ns = p.parse_args()
    feats: list[str] = list(ns.features)
    if ns.features_csv:
        feats.extend(x.strip() for x in ns.features_csv.split(",") if x.strip())
    seen: set[str] = set()
    ordered: list[str] = []
    for f in feats:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    if not ordered:
        print("no features requested")
        return 0
    if "magisk" in seen and "supersu" in seen:
        raise SystemExit("magisk and supersu are mutually exclusive")
    handlers = {
        "houdini": stage_houdini,
        "mindthegapps": stage_mindthegapps,
        "magisk": stage_magisk,
        "supersu": stage_supersu,
    }
    for f in ordered:
        handlers[f](EXTRAS / f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
