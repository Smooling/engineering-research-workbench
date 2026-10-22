"""v260923 · 统一路径解析：打包为 exe 后正确区分「可写数据」与「只读资源」。

- DATA_ROOT：可写数据根（config/、Workspace/ 等）。
  PyInstaller onefile 下 __file__ 指向临时解压目录，退出即被清空，
  因此 frozen 时改用 exe 所在目录（便携式，数据随 exe 走）。
- ASSET_ROOT：只读资源根（web/、VERSION）。frozen 时为 PyInstaller
  解压目录 sys._MEIPASS。
"""
from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    # exe 所在目录（便携式数据）
    DATA_ROOT = Path(sys.executable).resolve().parent
    # PyInstaller onefile 运行时解压目录
    ASSET_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    DATA_ROOT = Path(__file__).resolve().parents[1]
    ASSET_ROOT = DATA_ROOT

__all__ = ["FROZEN", "DATA_ROOT", "ASSET_ROOT"]
