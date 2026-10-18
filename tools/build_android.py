"""Build a signed debug APK with the checked-in Gradle wrapper."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="构建科研工作台 Android 预览安装包")
    parser.add_argument("--output", type=Path, default=ROOT / "build/android/ResearchWorkbench-Android-preview.apk")
    parser.add_argument("--clean", action="store_true", help="先清理 Gradle 中间产物")
    args = parser.parse_args()
    wrapper = ROOT / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    command = [str(wrapper), "--no-daemon", *(["clean"] if args.clean else []),
               "assembleDebug", "lintDebug", "--console=plain"]
    if os.name == "nt":
        command = ["cmd", "/c", *command]
    subprocess.run(command, cwd=ROOT / "android", check=True)
    source = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, args.output)
    print(f"APK: {args.output.resolve()} ({args.output.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
