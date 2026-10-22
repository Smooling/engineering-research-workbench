"""单文件包（`.zip`）解包 —— PLUGIN_SPEC §2「解包规则」与 §12 P-A/P-B 的落地。

规范原文见 `docs/PLUGIN_SPEC.md` §2，这里是它的执行体，六条规则逐条对应：

1. **先临时后原子**：解到 `plugins/.unpack-<id>-<version>/`，校验通过后 `rename` 为
   `plugins/<id>/`（同盘改名是原子的）——任何时刻都不存在「半解包」状态。
2. **一包一插件**：`plugin.json` 必须在包根；只在子目录里有清单 → 拒收。
3. **目录名 = manifest id**：落点由 **manifest 里的 `id`** 决定（不是文件名），
   所以改名之后目录名与 id 天然一致（P018 的即时满足由构造保证）。
4. **版本替换不合并**：目标已存在且版本不同 → 旧目录**整体**移入
   `System/Trash/plugins/<id>-<旧版本>/`，再放入新版；绝不逐文件覆盖。
5. **不覆盖用户手改目录**：目标目录存在但**没有本模块写的标记** → 视为用户手放的
   目录态插件，只报冲突，一个字节都不动。
6. **路径安全**：拒绝绝对路径 / 盘符 / UNC / `..` 穿越 / 符号链接条目，落点必须严格
   在目标目录内；另加条目数与解压体积上限（zip 炸弹）。

本模块**只动文件系统**：不 import 插件代码、不写 `System/plugins.json`
（§1：目录决定「在不在」，`plugins.json` 决定「开不开」）、不删用户的包文件。
解包成功后交给 `registry.discover` 正常扫描，剩下的校验/依赖/冲突判定复用同一套逻辑。

**已知边界（不做加锁）**：两个进程同时解同一个包时可能撞在同一临时目录上，此时其中一方
会得到「无法把临时目录改名」的拒收结果——目标目录永远不会处于半解包状态，重跑一次即可。
单用户桌面场景（一个 `server.py` 实例）不会遇到；刻意不引入文件锁，避免新增跨平台失败面。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import manifest as M

#: 由本模块解出的插件目录里的标记文件（规则 5 靠它区分「解出来的」与「手放的」）
MARKER = ".erw-unpacked"
#: 临时解包目录前缀（`.` 开头 → `discover()` 本来就跳过，不会被当成插件）
TEMP_PREFIX = ".unpack-"
#: 旧版本回收站（相对工作区）
TRASH_PARTS = ("System", "Trash", "plugins")
#: 僵尸临时目录的清理门槛（小时）：正常解包是秒级，超过这个时长说明是一次崩溃残留
STALE_TEMP_HOURS = 24

#: 防 zip 炸弹：条目数 / 解压后总字节 / 解压比上限
MAX_ENTRIES = 20000
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_RATIO = 200
#: 小包不查解压比（比值在极小体积下没有意义）
RATIO_MIN_BYTES = 8 * 1024 * 1024

_ABS_PATH_RE = re.compile(r"^(/|\\)|^[A-Za-z]:")

#: action 取值
ACTIONS = {
    "unpacked": "已解包安装",
    "upgraded": "已升级（旧版进回收站）",
    "current": "已是该版本，未改动",
    "conflict": "冲突，未改动任何文件",
    "rejected": "拒收，未改动任何文件",
}


class UnpackError(Exception):
    """解包过程中的可控失败（规则 2/6 与安全上限），消息直接面向用户。"""


@dataclass
class UnpackOutcome:
    """一个包的处理结果（失败也是结果，不抛给调用方）。"""

    file: str
    id: str = ""
    version: str = ""
    action: str = ""
    reason: str = ""
    dir: str = ""

    @property
    def changed(self) -> bool:
        return self.action in ("unpacked", "upgraded")

    def note(self) -> str:
        label = ACTIONS.get(self.action, self.action)
        head = f"单文件包 `{self.file}`：{label}"
        if self.id:
            head += f"（{self.id} {self.version}）"
        return f"{head} —— {self.reason}" if self.reason else head

    def as_dict(self) -> dict:
        return {
            "file": self.file, "id": self.id, "version": self.version,
            "action": self.action, "action_label": ACTIONS.get(self.action, self.action),
            "reason": self.reason, "dir": self.dir,
        }


def _norm(name: str) -> str:
    return name.replace("\\", "/").lstrip("./")


def _read_marker(target: Path) -> dict | None:
    """读「由 zip 解出」的标记；不存在/读不动 → None（视作用户手放）。"""
    path = target / MARKER
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_marker(target: Path, pid: str, version: str, source: str) -> None:
    (target / MARKER).write_text(
        json.dumps(
            {"id": pid, "version": version, "source": source,
             "unpacked": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )


def _trash(target: Path, workspace: Path | None, pid: str, old_version: str) -> Path | None:
    """把旧版本目录**整体**移入回收站（规则 4）。没有工作区 → 返回 None（调用方拒改）。"""
    if workspace is None:
        return None
    root = Path(workspace).joinpath(*TRASH_PARTS)
    name = f"{pid}-{old_version}" if old_version else pid
    dest = root / name
    if dest.exists():  # 同一版本被替换两次：加时间戳，绝不覆盖回收站里的东西
        dest = root / f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(dest))
    except OSError:
        return None
    return dest


def _safe_extract(zf: zipfile.ZipFile, dest: Path, pkg: Path) -> None:
    """规则 6：路径安全 + 体积上限，逐条校验后再写盘。"""
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise UnpackError(f"包内条目 {len(infos)} 个，超过上限 {MAX_ENTRIES}（防 zip 炸弹）")
    total = sum(max(0, i.file_size) for i in infos)
    if total > MAX_TOTAL_BYTES:
        raise UnpackError(
            f"解压后共 {total / 1048576:.1f} MB，超过上限 {MAX_TOTAL_BYTES / 1048576:.0f} MB"
        )
    compressed = sum(max(0, i.compress_size) for i in infos) or 1
    if total >= RATIO_MIN_BYTES and total / compressed > MAX_RATIO:
        raise UnpackError(f"解压比 {total / compressed:.0f}:1 超过上限 {MAX_RATIO}:1（防 zip 炸弹）")

    root = Path(dest).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for info in infos:
        raw = str(info.filename)
        if _ABS_PATH_RE.match(raw.replace("\\", "/")):
            raise UnpackError(f"包内出现绝对路径：{raw}（规则 6）")
        parts = PurePosixPath(raw.replace("\\", "/")).parts
        if ".." in parts:
            raise UnpackError(f"包内出现 `..` 穿越：{raw}（规则 6）")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise UnpackError(f"包内出现符号链接：{raw}（规则 6）")
        if not parts:
            continue
        out = root.joinpath(*parts)
        if out != root and root not in out.resolve().parents:
            raise UnpackError(f"包内路径逃出插件目录：{raw}（规则 6）")
        if info.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 16)


def _package_manifest(zf: zipfile.ZipFile) -> tuple[dict, str]:
    """规则 2：清单必须在包根；返回 (manifest, 错误消息)。"""
    names = [_norm(n) for n in zf.namelist()]
    key = next((raw for raw, norm in zip(zf.namelist(), names) if norm == "plugin.json"), None)
    if key is None:
        nested = next((n for n in names if n.endswith("/plugin.json")), "")
        if nested:
            return {}, (f"`plugin.json` 在子目录 `{nested.rsplit('/', 1)[0]}/` 里——"
                        "必须在包根（规则 2：一包一插件）")
        return {}, "包里没有 `plugin.json`（规则 2：一包一插件，清单必须在根）"
    try:
        data = json.loads(zf.read(key).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"包根 `plugin.json` 不是合法 JSON：{exc}"
    if not isinstance(data, dict):
        return {}, "包根 `plugin.json` 顶层必须是对象"
    return data, ""


def _staged_issues(tmp: Path, data: dict) -> list[dict]:
    """解包后从**盘上复核**（含 panel/style/entry 文件是否真的存在）。

    临时目录名是 `.unpack-<id>-<version>`，与 id 不同，P018 必然误报——过滤掉它：
    改名之后目录名就是 `<pid>`，这条由构造保证，不是需要检查的条件。
    """
    staged, issues = M.load_manifest(tmp)
    issues = list(issues) + list(M.validate(staged if staged is not None else data, plugin_dir=tmp))
    return [i for i in issues if i.get("code") != "P018"]


def install_package(pkg: Path, root: Path, *, workspace: Path | None = None) -> UnpackOutcome:
    """处理一个 `<id>-<version>.zip`：安装 / 升级 / 报冲突。永不抛异常给调用方前先落盘。"""
    pkg = Path(pkg)
    root = Path(root)
    try:
        zf = zipfile.ZipFile(pkg)
    except (zipfile.BadZipFile, OSError) as exc:
        return UnpackOutcome(file=pkg.name, action="rejected", reason=f"不是可读的 zip：{exc}")

    with zf:
        data, err = _package_manifest(zf)
        if err:
            return UnpackOutcome(file=pkg.name, action="rejected", reason=err)
        issues = M.validate(data)
        if M.errors(issues):
            return UnpackOutcome(file=pkg.name, action="rejected",
                                 reason="manifest 校验不过：" + M.summarize(issues))
        pid = str(data.get("id") or "").strip()
        version = str(data.get("version") or "").strip()

        target = root / pid
        marker = _read_marker(target) if target.is_dir() else None
        if target.exists():
            if not target.is_dir():
                return UnpackOutcome(file=pkg.name, id=pid, version=version, action="conflict",
                                     reason=f"`plugins/{pid}` 已存在且不是目录，不动它")
            if marker is None:
                return UnpackOutcome(
                    file=pkg.name, id=pid, version=version, action="conflict",
                    reason=(f"`plugins/{pid}/` 不是由 zip 解出的（多半是你自己放的目录态插件）："
                            "按规则 5 只提示、不覆盖；要装这个包请先自行移走该目录"),
                )
            if str(marker.get("version") or "") == version:
                return UnpackOutcome(file=pkg.name, id=pid, version=version, action="current",
                                     dir=str(target), reason="由同一个包解出，未改动")

        tmp = root / f"{TEMP_PREFIX}{pid}-{version}"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        try:
            _safe_extract(zf, tmp, pkg)
        except (UnpackError, OSError) as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            return UnpackOutcome(file=pkg.name, id=pid, version=version, action="rejected",
                                 reason=str(exc))

        staged = _staged_issues(tmp, data)
        if M.errors(staged):
            shutil.rmtree(tmp, ignore_errors=True)
            return UnpackOutcome(file=pkg.name, id=pid, version=version, action="rejected",
                                 reason="解出的内容校验不过：" + M.summarize(staged))

        action = "unpacked"
        if target.exists():
            trashed = _trash(target, workspace, pid, str(marker.get("version") or ""))
            if trashed is None:
                shutil.rmtree(tmp, ignore_errors=True)
                return UnpackOutcome(
                    file=pkg.name, id=pid, version=version, action="conflict",
                    reason=(f"`plugins/{pid}/` 已是另一版本，但没有可用工作区把旧版移入回收站，"
                            "拒绝逐文件覆盖（规则 4）"),
                )
            action = "upgraded"
        try:
            tmp.rename(target)  # 规则 1：同盘原子改名
        except OSError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            return UnpackOutcome(file=pkg.name, id=pid, version=version, action="rejected",
                                 reason=f"无法把临时目录改名为 `plugins/{pid}/`：{exc}")
        _write_marker(target, pid, version, pkg.name)
        return UnpackOutcome(file=pkg.name, id=pid, version=version, action=action,
                             dir=str(target),
                             reason="旧版已移入回收站，未做逐文件合并" if action == "upgraded" else "")


def _sweep_stale(root: Path) -> None:
    """清掉崩溃残留的 `.unpack-*` 临时目录（只清超过 STALE_TEMP_HOURS 的，避免与并发进程打架）。"""
    cutoff = datetime.now().timestamp() - STALE_TEMP_HOURS * 3600
    for entry in root.glob(f"{TEMP_PREFIX}*"):
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def unpack_all(root: Path | str, *, workspace: Path | None = None) -> list[UnpackOutcome]:
    """扫描一个插件根下的所有 `*.zip` 并逐个处理（单包失败不影响其他包，对齐 I4）。

    **只读根不动**：随包库（打包态的 `_MEIPASS/plugins`）是只读的，里面若有包只给一条
    提示，不会尝试写入。
    """
    root = Path(root)
    packages = sorted(root.glob("*.zip")) if root.is_dir() else []
    if not packages:
        return []
    if not os.access(root, os.W_OK):
        return [UnpackOutcome(file=p.name, action="conflict",
                              reason="该扫描根只读（随包库），包不会被解包")
                for p in packages]
    _sweep_stale(root)
    out: list[UnpackOutcome] = []
    for pkg in packages:
        try:
            out.append(install_package(pkg, root, workspace=workspace))
        except Exception as exc:  # 兜底：任何未预期异常都只影响这一个包
            out.append(UnpackOutcome(file=pkg.name, action="rejected",
                                     reason=f"{type(exc).__name__}: {exc}"))
    return out
