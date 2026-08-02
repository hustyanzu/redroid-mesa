#!/usr/bin/env bash
# Host helper: disable SuperSU root on a running redroid via adb.
set -euo pipefail
ADB=${ADB:-adb -s 127.0.0.1:5555}
$ADB root >/dev/null
sleep 0.4
$ADB remount >/dev/null 2>&1 || $ADB shell 'mount -o remount,rw /' >/dev/null
$ADB shell /system/bin/super-root-off
