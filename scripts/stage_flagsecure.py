#!/usr/bin/env python3
"""Patch services.jar to ignore FLAG_SECURE (isSecureLocked → false).

CI / offline: copies pre-built overlay from vendor/flagsecure/ (no docker run).

Live rebuild (FLAGSECURE_REBUILD=1): FlagSecurePatcher paccer inside base image,
then dex2oat on a booted redroid (FLAGSECURE_ADB / FLAGSECURE_DEX_CONTAINER).

Only isSecureLocked is patched. Do NOT patch isScreenCaptureAllowed /
getScreenCaptureDisabled — those break screencap (returns empty frames).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DL = ROOT / "third_party" / "downloads"
EXTRAS = ROOT / "out" / "extras"
VENDOR = ROOT / "vendor" / "flagsecure"

FLAGSECURE_VERSION = "r17"
FLAGSECURE_URL = (
    "https://github.com/j-hc/FlagSecurePatcher/releases/download/"
    f"{FLAGSECURE_VERSION}/flag-secure-patcher-{FLAGSECURE_VERSION}.zip"
)
FLAGSECURE_MD5 = "627912d0ce869d991e857792ac500ab0"

# Host tool arch inside the Magisk module (not the oat ISA).
PACCER_ARCH = "x64"
# Redroid A13 on this host is x86_64.
OAT_ISA = "x86_64"

# Only this method — see roidy patch-flag-secure.sh warning.
SERVICES_PATCHES = "isSecureLocked:RET_FALSE;"


def md5_file(path: Path) -> str:
    import hashlib

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
        ["curl", "-fL", "--retry", "5", "--retry-all-errors", "-C", "-", "-o", str(tmp), url],
        check=True,
    )
    got = md5_file(tmp)
    if got != expect_md5:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"md5 mismatch for {dest.name}: {got} != {expect_md5}")
    tmp.replace(dest)
    return dest


def docker_cmd(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=True, text=True, **kwargs)


def extract_services_jar(base_image: str, dest: Path) -> None:
    print(f"extract services.jar from {base_image}")
    cid = subprocess.check_output(["docker", "create", base_image], text=True).strip()
    try:
        docker_cmd(["cp", f"{cid}:/system/framework/services.jar", str(dest)])
    finally:
        subprocess.run(["docker", "rm", "-f", cid], check=False, capture_output=True)


def android_sh(base_image: str, work: Path, fsp: Path, script: str) -> None:
    """Run a shell script inside the image with Android bootstrap linker."""
    docker_cmd(
        [
            "run",
            "--rm",
            "--entrypoint",
            "/system/bin/bootstrap/linker64",
            "-v",
            f"{fsp}:/fsp:ro",
            "-v",
            f"{work}:/work",
            base_image,
            "/system/bin/sh",
            "-c",
            script,
        ]
    )


def patch_jar(base_image: str, jar_in: Path, jar_out: Path, fsp_root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="flagsecure-jar-") as td:
        td_path = Path(td)
        jar_dir = td_path / "jar"
        jar_dir.mkdir()
        with zipfile.ZipFile(jar_in) as z:
            z.extractall(jar_dir)
        if not (jar_dir / "classes.dex").is_file():
            raise SystemExit("services.jar missing classes.dex")

        work = td_path / "work"
        work.mkdir()
        shutil.copytree(jar_dir, work / "jar")

        patch_script = f"""
set -e
LINKER=/system/bin/bootstrap/linker64
export LD_LIBRARY_PATH=/fsp/util/lib/{PACCER_ARCH}
P=/fsp/util/bin/{PACCER_ARCH}/paccer
PATCHES='{SERVICES_PATCHES}'
ok=0
for DEX in /work/jar/classes*; do
  name=${{DEX##*/}}
  echo "=== paccer $name ==="
  out=$($LINKER "$P" "$DEX" "$DEX" "$PATCHES" 2>&1) || {{
    echo "paccer fail: $out"
    exit 1
  }}
  echo "$out"
  [ -n "$out" ] && ok=1
done
[ "$ok" = 1 ] || {{ echo "no method patched"; exit 1; }}
echo PATCH_OK
"""
        android_sh(base_image, work, fsp_root, patch_script)

        # Store-only zip like FlagSecurePatcher, then zipalign.
        patched_zip = work / "services-patched.zip"
        subprocess.run(
            ["zip", "-q0r", str(patched_zip), "."],
            cwd=work / "jar",
            check=True,
        )
        (work / "out").mkdir()
        align_script = f"""
set -e
LINKER=/system/bin/bootstrap/linker64
export LD_LIBRARY_PATH=/fsp/util/lib/{PACCER_ARCH}
$LINKER /fsp/util/bin/{PACCER_ARCH}/zipalign -p -z 4 \\
  /work/services-patched.zip /work/out/services.jar
echo ZIPALIGN_OK
"""
        android_sh(base_image, work, fsp_root, align_script)
        shutil.copy2(work / "out" / "services.jar", jar_out)
        print(f"patched jar → {jar_out}")


def dex2oat_via_adb(jar: Path, oat_dir: Path, serial: str) -> None:
    print(f"dex2oat via adb ({serial})")
    remote = "/data/local/tmp/flagsecure-build"
    subprocess.run(["adb", "connect", serial], check=False, capture_output=True)
    subprocess.run(["adb", "-s", serial, "wait-for-device"], check=True)
    subprocess.run(["adb", "-s", serial, "root"], check=False, capture_output=True)
    subprocess.run(["adb", "-s", serial, "wait-for-device"], check=True)
    subprocess.run(
        ["adb", "-s", serial, "shell", f"rm -rf {remote} && mkdir -p {remote}/oat/{OAT_ISA}"],
        check=True,
    )
    subprocess.run(
        ["adb", "-s", serial, "push", str(jar), f"{remote}/services.jar"],
        check=True,
    )
    cmd = (
        f"dex2oat --dex-file={remote}/services.jar --android-root=/system "
        f"--instruction-set={OAT_ISA} "
        f"--oat-file={remote}/oat/{OAT_ISA}/services.odex "
        f"--app-image-file={remote}/oat/{OAT_ISA}/services.art "
        f"--no-generate-debug-info --generate-mini-debug-info"
    )
    subprocess.run(["adb", "-s", serial, "shell", cmd], check=True)
    oat_dir.mkdir(parents=True, exist_ok=True)
    for name in ("services.odex", "services.vdex", "services.art"):
        src = f"{remote}/oat/{OAT_ISA}/{name}"
        dest = oat_dir / name
        r = subprocess.run(["adb", "-s", serial, "pull", src, str(dest)], capture_output=True)
        if r.returncode != 0 and name == "services.art":
            print("note: services.art missing (ok)")
            continue
        if r.returncode != 0:
            raise SystemExit(f"adb pull failed: {src}\n{r.stderr.decode()}")
    subprocess.run(["adb", "-s", serial, "shell", f"rm -rf {remote}"], check=False)


def dex2oat_bin_for_container(container: str) -> str:
    probe = (
        "for p in /apex/com.android.art/bin/dex2oat64 "
        "/apex/com.android.art/bin/dex2oat /system/bin/dex2oat; do "
        "[ -x \"$p\" ] && echo \"$p\" && exit 0; done; exit 1"
    )
    out = subprocess.check_output(
        ["docker", "exec", container, "/system/bin/sh", "-c", probe],
        text=True,
    ).strip()
    if not out:
        raise SystemExit(f"dex2oat not found in container {container}")
    return out.splitlines()[-1]


def dex2oat_via_docker_exec(jar: Path, oat_dir: Path, container: str) -> None:
    print(f"dex2oat via docker exec ({container})")
    remote = "/data/local/tmp/flagsecure-build"
    d2o = dex2oat_bin_for_container(container)
    env_prefix = (
        "export PATH=/product/bin:/apex/com.android.runtime/bin:/apex/com.android.art/bin:"
        "/system_ext/bin:/system/bin:/system/xbin:/odm/bin:/vendor/bin:/vendor/xbin; "
        "export ANDROID_DATA=/data ANDROID_ROOT=/system; "
    )
    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "/system/bin/sh",
            "-c",
            env_prefix + f"rm -rf {remote} && mkdir -p {remote}/oat/{OAT_ISA}",
        ],
        check=True,
    )
    subprocess.run(["docker", "cp", str(jar), f"{container}:{remote}/services.jar"], check=True)
    cmd = (
        env_prefix
        + f"{d2o} --dex-file={remote}/services.jar --android-root=/system "
        f"--instruction-set={OAT_ISA} "
        f"--oat-file={remote}/oat/{OAT_ISA}/services.odex "
        f"--app-image-file={remote}/oat/{OAT_ISA}/services.art "
        f"--no-generate-debug-info --generate-mini-debug-info"
    )
    subprocess.run(
        ["docker", "exec", container, "/system/bin/sh", "-c", cmd],
        check=True,
    )
    oat_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="flagsecure-oat-") as td:
        td_path = Path(td)
        subprocess.run(
            ["docker", "cp", f"{container}:{remote}/oat/{OAT_ISA}/.", str(td_path)],
            check=True,
        )
        for name in ("services.odex", "services.vdex", "services.art"):
            src = td_path / name
            if not src.is_file():
                if name == "services.art":
                    print("note: services.art missing (ok)")
                    continue
                raise SystemExit(f"missing {name} after dex2oat")
            shutil.copy2(src, oat_dir / name)
    subprocess.run(
        ["docker", "exec", container, "/system/bin/sh", "-c", f"rm -rf {remote}"],
        check=False,
    )


def resolve_dex2oat(jar: Path, oat_dir: Path) -> None:
    # Prefer adb: it injects a proper Android environment (PATH / ANDROID_*).
    serial = os.environ.get("FLAGSECURE_ADB", "127.0.0.1:5555").strip()
    if serial and shutil.which("adb"):
        try:
            dex2oat_via_adb(jar, oat_dir, serial)
            return
        except (subprocess.CalledProcessError, SystemExit) as e:
            print(f"flagsecure: adb dex2oat failed ({e}); trying docker exec")

    container = os.environ.get("FLAGSECURE_DEX_CONTAINER", "").strip()
    if not container:
        try:
            out = subprocess.check_output(
                ["docker", "ps", "--format", "{{.Names}}"],
                text=True,
            )
            for name in ("redroid-mesa-1", "redroid-mesa-2", "redroid-mesa"):
                if name in out.splitlines():
                    container = name
                    break
        except (subprocess.CalledProcessError, FileNotFoundError):
            container = ""

    if container:
        dex2oat_via_docker_exec(jar, oat_dir, container)
        return

    raise SystemExit(
        "flagsecure: need dex2oat host — set FLAGSECURE_ADB "
        "or FLAGSECURE_DEX_CONTAINER (booted redroid)"
    )


def load_vendor_manifest() -> dict[str, str]:
    mf = VENDOR / "manifest.env"
    if not mf.is_file():
        return {}
    data: dict[str, str] = {}
    for line in mf.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        data[key.strip()] = val.strip()
    return data


def vendor_matches(base_image: str) -> bool:
    m = load_vendor_manifest()
    if not m:
        return False
    jar = VENDOR / "system" / "framework" / "services.jar"
    if not jar.is_file():
        return False
    if m.get("BASE_IMAGE") != base_image:
        return False
    if m.get("FLAGSECURE_VERSION") != FLAGSECURE_VERSION:
        return False
    expect = m.get("SERVICES_JAR_MD5", "")
    if expect and md5_file(jar) != expect:
        raise SystemExit(f"vendor flagsecure jar md5 mismatch (expected {expect})")
    return True


def merge_tree(src: Path, dst: Path) -> None:
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            s = Path(root) / name
            d = target_dir / name
            shutil.copy2(s, d)


def stage_from_vendor(out: Path, *, jar_only: bool) -> None:
    src = VENDOR / "system"
    if not src.is_dir():
        raise SystemExit(f"missing {src}")
    merge_tree(src, out / "system")
    if jar_only:
        oat = out / "system" / "framework" / "oat"
        if oat.exists():
            shutil.rmtree(oat)
        (out / ".no_oat").write_text("1\n")
    print(f"staged flagsecure from vendor → {out}" + (" (jar only)" if jar_only else ""))


def stage_flagsecure(out: Path, *, base_image: str) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    skip_oat = os.environ.get("FLAGSECURE_SKIP_DEX2OAT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    rebuild = os.environ.get("FLAGSECURE_REBUILD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    if skip_oat:
        if not vendor_matches(base_image):
            raise SystemExit(
                "flagsecure: CI needs vendor/flagsecure for "
                f"{base_image} (FLAGSECURE_VERSION={FLAGSECURE_VERSION})"
            )
        stage_from_vendor(out, jar_only=True)
        return

    if not rebuild and vendor_matches(base_image):
        stage_from_vendor(out, jar_only=False)
        return

    fw = out / "system" / "framework"
    oat = fw / "oat" / OAT_ISA
    fw.mkdir(parents=True)
    marker_dir = out / "system" / "etc" / "redroid-mesa"
    marker_dir.mkdir(parents=True)

    z = ensure_download(
        FLAGSECURE_URL,
        DL / f"flag-secure-patcher-{FLAGSECURE_VERSION}.zip",
        FLAGSECURE_MD5,
    )
    with tempfile.TemporaryDirectory(prefix="flagsecure-fsp-") as td:
        fsp_root = Path(td) / "fsp"
        fsp_root.mkdir()
        with zipfile.ZipFile(z) as zf:
            zf.extractall(fsp_root)
        paccer = fsp_root / "util" / "bin" / PACCER_ARCH / "paccer"
        if not paccer.is_file():
            raise SystemExit(f"paccer missing in module ({paccer})")

        with tempfile.TemporaryDirectory(prefix="flagsecure-stage-") as sd:
            sd_path = Path(sd)
            jar_in = sd_path / "services.jar.in"
            jar_out = sd_path / "services.jar"
            extract_services_jar(base_image, jar_in)
            patch_jar(base_image, jar_in, jar_out, fsp_root)
            resolve_dex2oat(jar_out, oat)
            shutil.copy2(jar_out, fw / "services.jar")

    oat_note = f"oat_isa={OAT_ISA}"
    (marker_dir / "flagsecure").write_text(
        f"isSecureLocked=RET_FALSE\nsource=FlagSecurePatcher-{FLAGSECURE_VERSION}\n"
        f"{oat_note}\n"
    )
    print(f"staged flagsecure (live rebuild) → {out}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--base-image",
        default=os.environ.get("BASE_IMAGE", "docker.io/redroid/redroid:13.0.0-latest"),
        help="image to extract services.jar from",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=EXTRAS / "flagsecure",
        help="stage destination (overlay root)",
    )
    ns = p.parse_args()
    stage_flagsecure(ns.out, base_image=ns.base_image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
