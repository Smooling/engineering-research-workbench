"""夹具共用的「用完还原」助手：只删本次新增的文件，目录按原状还原。

为什么需要：插件的 `register()` 会通过 `ctx.storage.ensure()` 合法地创建自己的命名空间目录，
夹具一旦执行过插件代码就会留下空目录；而「目录原先不存在才 rmtree」的写法在**第二次运行**时失效
（目录已存在 → 不删 → 上次导出的文件/快照状态留在用户 Workspace 里）。

用法：
    before = snap(ws_plugin_dir)
    ... 跑夹具 ...
    restore(ws_plugin_dir, before)
"""

from __future__ import annotations

import shutil
from pathlib import Path


def snap(path: Path) -> tuple[bool, set[str]]:
    """记录 (目录原来是否存在, 原有文件的相对路径集合)。"""
    path = Path(path)
    if not path.is_dir():
        return (False, set())
    return (True, {str(p.relative_to(path)).replace("\\", "/") for p in path.rglob("*") if p.is_file()})


def restore(path: Path, before: tuple[bool, set[str]]) -> list[str]:
    """还原：删掉本次新增的文件；目录按原状还原。

    目录级规则（空目录没有数据，插件的 `storage.ensure()` 会按需重建，所以可以放心删）：
    - 原先不存在 → 整个删掉；
    - 原先存在但**一个文件都没有**，且现在也没有文件 → 整个删掉（避免空目录在多次夹具运行间越攒越多）；
    - 原先有文件 → 只清掉本次新增的文件与空子目录。
    """
    path = Path(path)
    existed, files = before
    if not path.exists():
        return []
    removed: list[str] = []
    for item in list(path.rglob("*")):
        if item.is_file():
            rel = str(item.relative_to(path)).replace("\\", "/")
            if rel not in files:
                item.unlink(missing_ok=True)
                removed.append(rel)
    if not existed or not files:
        if not any(p.is_file() for p in path.rglob("*")):
            shutil.rmtree(path, ignore_errors=True)
            return removed
    for folder in sorted((p for p in path.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            folder.rmdir()
        except OSError:
            pass
    return removed


def snap_many(paths) -> dict[str, tuple[bool, set[str]]]:
    return {str(Path(p)): snap(Path(p)) for p in paths}


def restore_many(records: dict[str, tuple[bool, set[str]]]) -> dict[str, list[str]]:
    return {key: restore(Path(key), value) for key, value in records.items()}
