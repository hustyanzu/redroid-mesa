#!/usr/bin/env python3
"""Stage system overlays: houdini / microg / magiskdelta → out/extras/<name>/

Downloads are cached under third_party/downloads/.
Houdini/microG follow ayasa520/redroid-script + casualsnek/waydroid_script.
Magisk is real Kitsune Mask (Jordan231111/KitsuneMagisk), not official Magisk.
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
# Real Kitsune Mask (Magisk Delta lineage, MagiskHide). Not ayasa520/official Magisk.
# Package: io.github.huskydg.magisk — binaries are libmagisk64.so (not libmagisk.so).
MAGISK_URL = (
    "https://github.com/Jordan231111/KitsuneMagisk/releases/download/"
    "v31.0-25fa2159/app-release.apk"
)
MAGISK_MD5 = "f3c819e276274f242f0e22921a73e2e7"
MICROG_URL = (
    "https://github.com/ayasa520/MinMicroG/releases/download/latest/"
    "MinMicroG-Standard-2.11.1-20230429100529.zip"
)
MICROG_MD5 = "0fe332a9caa3fbb294f2e2b50f720c6b"

ANDROID_VER = "13.0.0"
SDK = 33

HOUDINI_RC = r"""
on early-init
    mount binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc

on property:ro.enable.native.bridge.exec=1
    copy /system/etc/binfmt_misc/arm_exe /proc/sys/fs/binfmt_misc/register
    copy /system/etc/binfmt_misc/arm_dyn /proc/sys/fs/binfmt_misc/register

on property:ro.enable.native.bridge.exec64=1
    copy /system/etc/binfmt_misc/arm64_exe /proc/sys/fs/binfmt_misc/register
    copy /system/etc/binfmt_misc/arm64_dyn /proc/sys/fs/binfmt_misc/register

# Do NOT replace /system/etc/init/hw/init.rc. Apply linker patches softly.
on property:apexd.status=activated
    exec -- /system/bin/sh -c "/system/bin/patch -N -r - /linkerconfig/ld.config.txt < /system/etc/ld_config.patch || true"
    exec -- /system/bin/sh -c "/system/bin/patch -N -r - /linkerconfig/com.android.media.swcodec/ld.config.txt < /system/etc/ld_config_swcodec.patch || true"

on property:sys.boot_completed=1
    exec -- /system/bin/sh -c "echo ':arm_exe:M::\\x7f\\x45\\x4c\\x46\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x28::/system/bin/houdini:P' >> /proc/sys/fs/binfmt_misc/register"
    exec -- /system/bin/sh -c "echo ':arm_dyn:M::\\x7f\\x45\\x4c\\x46\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x03\\x00\\x28::/system/bin/houdini:P' >> /proc/sys/fs/binfmt_misc/register"
    exec -- /system/bin/sh -c "echo ':arm64_exe:M::\\x7f\\x45\\x4c\\x46\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\xb7::/system/bin/houdini64:P' >> /proc/sys/fs/binfmt_misc/register"
    exec -- /system/bin/sh -c "echo ':arm64_dyn:M::\\x7f\\x45\\x4c\\x46\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x03\\x00\\xb7::/system/bin/houdini64:P' >> /proc/sys/fs/binfmt_misc/register"
"""

# Own init file — never overwrite stock bootanim.rc / hw/init.rc.
# Kitsune ships magisk64; setup-sbin then provides /sbin/magisk.
MAGISK_RC = """
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
    exec -- /system/bin/sh -c "if [ ! -e /data/data/io.github.huskydg.magisk ] ; then pm install /system/etc/init/magisk/magisk.apk ; fi"

on property:init.svc.zygote=restarting
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --zygote-restart

on property:init.svc.zygote=stopped
    exec u:r:su:s0 root root -- /sbin/magisk --auto-selinux --zygote-restart
"""

MICROG_RC = """
on property:sys.boot_completed=1
    start microg_service

service microg_service /system/bin/sh /system/bin/npem
    user root
    group root
    oneshot
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
    cmd = [
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
    ]
    subprocess.run(cmd, check=True)
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

    # Only take ld_config*.patch from the hack — never replace hw/init.rc.
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

    rc = out / "system/etc/init/houdini.rc"
    rc.parent.mkdir(parents=True, exist_ok=True)
    rc.write_text(HOUDINI_RC.lstrip("\n"))
    os.chmod(rc, 0o644)
    # Ensure we did not stage a replacement init.rc
    bad = out / "system/etc/init/hw/init.rc"
    if bad.exists():
        bad.unlink()
    print(f"staged houdini → {out}")


def stage_magiskdelta(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    magisk_dir = out / "system/etc/init/magisk"
    magisk_dir.mkdir(parents=True)
    (out / "sbin").mkdir(parents=True, exist_ok=True)

    apk = ensure_download(MAGISK_URL, DL / "magisk.apk", MAGISK_MD5)
    with tempfile.TemporaryDirectory(prefix="magisk-") as td:
        td_path = Path(td)
        unzip_to(apk, td_path / "apk")
        lib_dir = td_path / "apk" / "lib" / "x86_64"
        if not lib_dir.is_dir():
            raise SystemExit("magisk x86_64 libs missing")
        for so in lib_dir.glob("lib*.so"):
            m = re.search(r"lib(.*)\.so", so.name)
            if not m:
                continue
            dest = magisk_dir / m.group(1)
            shutil.copyfile(so, dest)
            os.chmod(dest, 0o755)
        # Kitsune: magisk64 only; keep a magisk alias for tooling that expects it.
        magisk64 = magisk_dir / "magisk64"
        magisk = magisk_dir / "magisk"
        if magisk64.is_file() and not magisk.is_file():
            shutil.copyfile(magisk64, magisk)
            os.chmod(magisk, 0o755)
        if not magisk64.is_file() and not magisk.is_file():
            raise SystemExit("magisk/magisk64 binary missing after extract")
    shutil.copyfile(apk, magisk_dir / "magisk.apk")

    # Dedicated magisk.rc — do not touch stock bootanim.rc
    rc = out / "system/etc/init/magisk.rc"
    rc.write_text(MAGISK_RC.lstrip("\n"))
    os.chmod(rc, 0o644)
    print(f"staged magiskdelta → {out}")


def extract_apk_native_libs(apk_path: Path, out_lib_parent: Path) -> None:
    """Extract lib/x86_64/*.so next to the APK (Android packaging convention)."""
    try:
        with zipfile.ZipFile(apk_path) as z:
            for name in z.namelist():
                if not name.startswith("lib/x86_64/") or not name.endswith(".so"):
                    continue
                base = Path(name).name
                dest_dir = out_lib_parent / "lib" / "x86_64"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / base
                with z.open(name) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile:
        pass


def stage_microg(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    z = ensure_download(MICROG_URL, DL / "MinMicroG-Standard.zip", MICROG_MD5)
    with tempfile.TemporaryDirectory(prefix="microg-") as td:
        td_path = Path(td)
        unzip_to(z, td_path / "u")
        src_system = td_path / "u" / "system"
        if not src_system.is_dir():
            # some zips nest an extra directory
            found = list((td_path / "u").glob("*/system"))
            if not found:
                raise SystemExit("MinMicroG system/ missing")
            src_system = found[0]

        arch = "x86_64"
        sub_arch = "x86"
        for root, dirs, files in os.walk(src_system):
            root_p = Path(root)
            dir_name = root_p.name
            flag = False
            if dir_name.startswith("-") and dir_name.endswith("-"):
                archs, sdks = [], []
                for part in dir_name.split("-"):
                    if not part:
                        continue
                    if part.isdigit():
                        sdks.append(part)
                    else:
                        archs.append(part)
                if (archs and arch not in archs and sub_arch not in archs) or (
                    sdks and str(SDK) not in sdks
                ):
                    continue
                flag = True

            for file in files:
                src_file = root_p / file
                if not flag:
                    rel = src_file.relative_to(src_system)
                else:
                    # unwrap -arch-sdk- directory
                    rel = (root_p.parent / file).relative_to(src_system)
                dst_file = out / "system" / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                if dst_file.suffix.lower() == ".apk":
                    extract_apk_native_libs(dst_file, dst_file.parent)

    rc = out / "system/etc/init/microg.rc"
    rc.parent.mkdir(parents=True, exist_ok=True)
    rc.write_text(MICROG_RC.lstrip("\n"))
    os.chmod(rc, 0o644)
    npem = out / "system/bin/npem"
    if npem.is_file():
        os.chmod(npem, 0o755)
    print(f"staged microg → {out}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "features",
        nargs="*",
        choices=["houdini", "microg", "magiskdelta"],
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
    handlers = {
        "houdini": stage_houdini,
        "microg": stage_microg,
        "magiskdelta": stage_magiskdelta,
    }
    for f in ordered:
        handlers[f](EXTRAS / f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
