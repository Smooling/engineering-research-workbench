"""Build a signed debug APK with the checked-in Gradle wrapper."""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify_backend(apk: Path) -> None:
    """Do not deliver a cached Python bundle which predates the current source."""
    expected = {"server.py": ROOT / "server.py",
                "android_runtime.py": ROOT / "android/app/src/main/python/android_runtime.py"}
    expected.update({p.relative_to(ROOT).as_posix(): p for p in (ROOT / "app").rglob("*.py")
                     if "__pycache__" not in p.parts})
    with zipfile.ZipFile(apk) as archive:
        with zipfile.ZipFile(io.BytesIO(archive.read("assets/chaquopy/app.imy"))) as source:
            names = set(source.namelist())
            for name, path in expected.items():
                if name not in names or source.read(name) != path.read_bytes() or name[:-3] + ".pyc" in names:
                    raise RuntimeError(f"APK 中的 Python 源码不匹配：{name}；请使用 --clean 重新构建")
    print(f"Verified {len(expected)} packaged Python source files against the repository")


def verify_frontend(apk: Path) -> None:
    """An APK must contain the current UI, not an older Gradle assets archive."""
    expected = [p for p in (ROOT / "web").rglob("*") if p.is_file()]
    expected += [ROOT / "VERSION", ROOT / "LICENSE.txt"]
    with zipfile.ZipFile(apk) as archive:
        with zipfile.ZipFile(io.BytesIO(archive.read("assets/workbench.zip"))) as assets:
            for path in expected:
                name = path.relative_to(ROOT).as_posix()
                if name not in assets.namelist() or assets.read(name) != path.read_bytes():
                    raise RuntimeError(f"APK 中的前端资源不匹配：{name}；请使用 --clean 重新构建")
    print(f"Verified {len(expected)} packaged frontend assets against the repository")


def main() -> None:
    parser = argparse.ArgumentParser(description="构建科研工作台 Android 预览安装包")
    parser.add_argument("--output", type=Path, default=ROOT / "build/android/ResearchWorkbench-Android-preview.apk")
    parser.add_argument("--clean", action="store_true", help="先清理 Gradle 中间产物")
    args = parser.parse_args()
    wrapper = ROOT / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    command = [str(wrapper), "--no-daemon", *(["clean", "--rerun-tasks", "--no-build-cache"] if args.clean else []),
               "assembleDebug", "lintDebug", "--console=plain"]
    if os.name == "nt":
        command = ["cmd", "/c", *command]
    subprocess.run(command, cwd=ROOT / "android", check=True)
    source = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    verify_backend(source)
    verify_frontend(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, args.output)
    print(f"APK: {args.output.resolve()} ({args.output.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
