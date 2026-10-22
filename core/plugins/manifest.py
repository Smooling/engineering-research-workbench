"""插件清单（`plugin.json`）的契约与校验。

唯一权威说明是 [docs/PLUGIN_SPEC.md](../../docs/PLUGIN_SPEC.md) §3（字段表）、§7（安全与校验清单）
与 §4（依赖）。本模块只做**声明式校验**：不加载插件代码、不碰插件目录里的执行入口，
因此可以在安装前、CLI 里、测试夹具上安全地跑。

规则码 `Pxxx`，形状与 `core/contracts` 一致：``{code, level, message, fix?}``，
``level=error`` 表示必须拒载（§7「任一不过 → 拒载并说明原因」）。

纯函数模块：只读文件、不写任何东西，也不依赖 `app`/`mcp`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

#: 内核 API 版本。新增/破坏性变更内核扩展点时才 +1（I7：不匹配直接拒载）
SUPPORTED_API_VERSION = 1

#: v1 支持的权限清单（PLUGIN_SPEC §7.6：声明了未支持权限 → 拒载）。
#: 扩展这个集合是**有意的动作**：每加一项都要在 §7 里写清它意味着什么、怎么被展示。
KNOWN_PERMISSIONS: dict[str, str] = {
    "net:http": "可访问网络（HTTP 请求）",
    "storage:own": "可写入自己的数据目录",
    "config:own": "可读写自己的配置",
    "ui:panel": "可注册前端面板（导航项 + 页面）",
    "process:spawn": "可拉起自己的独立进程",
    "llm:use": "可调用内核已配置的模型（消耗用量）",
}

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
#: 语义化版本（容忍 `1.0` 这种缺 patch 的写法，缺位按 0 比）
SEMVER_RE = re.compile(r"^\d+\.\d+(\.\d+)?([-+][0-9A-Za-z.-]+)?$")
TOOL_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CORE_MIN_RE = re.compile(r"^v?\d+(\.\d+)*$")
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

#: 前端槽位（§6.3）：内核提供挂载点，插件把组件画进去，不改内核 DOM。
#: 与 `web/app.js` 的 `ERWPanels.SLOTS` 对应；加槽位是**有意的动作**（须同步 PLUGIN_SPEC §6.3）。
KNOWN_SLOTS: frozenset[str] = frozenset({"topbar", "overlay"})


def _issue(code: str, level: str, message: str, fix: str = "") -> dict[str, str]:
    out = {"code": code, "level": level, "message": message}
    if fix:
        out["fix"] = fix
    return out


def read_core_version(root) -> str:
    """读 `VERSION` 文件作为内核版本（**去掉 UTF-8 BOM**，读不到返回空串）。

    为什么要单独一个函数：`VERSION` 曾被 PowerShell 以带 BOM 的 UTF-8 写出，
    变成 `"\\ufeffv261009.9"`，于是 `core_min` 比较全线失败、**所有插件被判为
    「内核版本过低」而阻塞**（实测：服务启动后插件路由全 404，而 CLI 因为另有一处
    `lstrip("\\ufeff")` 看起来一切正常）。集中在这里处理，所有读取方共用。
    """
    from pathlib import Path

    try:
        raw = (Path(root) / "VERSION").read_text(encoding="utf-8")
    except OSError:
        return ""
    return raw.lstrip("\ufeff").strip()


def version_tuple(text: str) -> tuple[int, ...]:
    """把 `v261009.0` / `1.0.0` 归一成可比较的整数元组。"""
    raw = str(text or "").strip().lstrip("vV")
    raw = re.split(r"[-+]", raw, 1)[0]
    parts: list[int] = []
    for chunk in raw.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


def _at_least(have: str, need: str) -> bool:
    a, b = version_tuple(have), version_tuple(need)
    size = max(len(a), len(b))
    a = a + (0,) * (size - len(a))
    b = b + (0,) * (size - len(b))
    return a >= b


def load_manifest(plugin_dir: Path) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """读 `plugin.json`；读不到/不是对象时返回 (None, issues)。"""
    path = Path(plugin_dir) / "plugin.json"
    if not path.is_file():
        return None, [_issue("P000", "error", "缺少 plugin.json", "每个插件目录必须有 plugin.json（唯一必需文件）")]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [_issue("P001", "error", f"plugin.json 无法解析：{exc}", "确认是合法 JSON（UTF-8，无尾随逗号）")]
    if not isinstance(data, dict):
        return None, [_issue("P001", "error", "plugin.json 顶层必须是对象", "")]
    return data, []


def validate(
    manifest: dict[str, Any] | None,
    *,
    plugin_dir: Path | None = None,
    core_version: str = "",
) -> list[dict[str, str]]:
    """校验一份 manifest，返回问题清单（空 = 通过）。"""
    issues: list[dict[str, str]] = []
    if not isinstance(manifest, dict):
        return [_issue("P001", "error", "manifest 不是对象", "")]

    pid = str(manifest.get("id") or "").strip()

    # P002 · id
    if not pid:
        issues.append(_issue("P002", "error", "缺少 id", "小写字母/数字/短横线，决定路由/工具/存储命名空间"))
    elif not ID_RE.match(pid):
        issues.append(_issue("P002", "error", f"id `{pid}` 不合法",
                             "只能是小写字母开头、由小写字母/数字/短横线组成，长度 2–40"))

    # P018 · 目录名必须等于 id（§2.3：避免「文件夹叫 A、插件自称 B」）
    if plugin_dir is not None and pid and Path(plugin_dir).name != pid:
        issues.append(_issue("P018", "error",
                             f"目录名 `{Path(plugin_dir).name}` 与 manifest id `{pid}` 不一致",
                             f"把目录改名为 `{pid}/`（或改 id），否则拒载"))

    # P003 · version
    version = str(manifest.get("version") or "").strip()
    if not version:
        issues.append(_issue("P003", "error", "缺少 version", "语义化版本，如 `1.0.0`"))
    elif not SEMVER_RE.match(version):
        issues.append(_issue("P003", "error", f"version `{version}` 不是语义化版本", "形如 `1.0.0` / `1.2`"))

    # P004 · api_version（I7）
    api_version = manifest.get("api_version")
    if api_version is None:
        issues.append(_issue("P004", "error", "缺少 api_version", f"当前内核支持 `{SUPPORTED_API_VERSION}`"))
    elif not isinstance(api_version, int) or isinstance(api_version, bool):
        issues.append(_issue("P004", "error", f"api_version 必须是整数，当前为 {api_version!r}", ""))
    elif api_version != SUPPORTED_API_VERSION:
        issues.append(_issue("P004", "error",
                             f"api_version={api_version} 与内核 {SUPPORTED_API_VERSION} 不匹配",
                             "升级插件到匹配内核 API 的版本（I7：不匹配直接拒载）"))

    # P005 · core_min
    core_min = str(manifest.get("core_min") or "").strip()
    if core_min:
        if not CORE_MIN_RE.match(core_min):
            issues.append(_issue("P005", "error", f"core_min `{core_min}` 格式不对", "形如 `v261010`"))
        elif core_version and not _at_least(core_version, core_min):
            issues.append(_issue("P005", "error",
                                 f"内核版本 {core_version} 低于插件要求的 {core_min}",
                                 "升级工作台，或使用与该内核匹配的插件版本"))

    # P006 / P007 / P008 · kind / distribution / default_enabled
    kind = str(manifest.get("kind") or "").strip()
    if not kind:
        issues.append(_issue("P006", "error", "缺少 kind", "`inprocess`（默认）或 `process`（独立进程）"))
    elif kind not in ("inprocess", "process"):
        issues.append(_issue("P006", "error", f"kind `{kind}` 不合法", "取值限定 `inprocess` / `process`"))

    distribution = str(manifest.get("distribution") or "").strip()
    if distribution and distribution not in ("bundled", "optional"):
        issues.append(_issue("P007", "error", f"distribution `{distribution}` 不合法",
                             "取值限定 `bundled`（随包）/ `optional`（可选）"))
    if "default_enabled" in manifest and not isinstance(manifest["default_enabled"], bool):
        issues.append(_issue("P008", "error", "default_enabled 必须是布尔值", ""))

    # P009 · entry
    entry = str(manifest.get("entry") or "").strip()
    if kind == "process" and not entry:
        issues.append(_issue("P009", "error", "kind=process 必须声明 entry", "如 `service.py`"))
    if entry:
        if Path(entry).is_absolute() or ".." in Path(entry).parts:
            issues.append(_issue("P009", "error", f"entry `{entry}` 必须是插件目录内的相对路径", ""))
        elif plugin_dir is not None and not (Path(plugin_dir) / entry).is_file():
            issues.append(_issue("P009", "error", f"entry 指向的文件不存在：{entry}", "补上该文件或改 entry"))

    # P010 · permissions
    permissions = manifest.get("permissions")
    if permissions is not None:
        if not isinstance(permissions, list):
            issues.append(_issue("P010", "error", "permissions 必须是数组", ""))
        else:
            unknown = [str(p) for p in permissions if str(p) not in KNOWN_PERMISSIONS]
            if unknown:
                issues.append(_issue("P010", "error", f"声明了内核不支持的权限：{unknown}",
                                     "当前支持：" + " / ".join(sorted(KNOWN_PERMISSIONS))))

    # P011 · routes：相对路径，且不得注册裸 /api/*
    routes = manifest.get("routes")
    if routes is not None:
        if not isinstance(routes, list):
            issues.append(_issue("P011", "error", "routes 必须是数组", ""))
        else:
            for item in routes:
                if not isinstance(item, dict):
                    issues.append(_issue("P011", "error", "routes 每项必须是对象", '如 `{"method":"GET","path":"forecast"}`'))
                    continue
                path = str(item.get("path") or "").strip()
                method = str(item.get("method") or "GET").strip().upper()
                if method not in HTTP_METHODS:
                    issues.append(_issue("P011", "error", f"路由方法 `{method}` 不支持", "GET/POST/PUT/PATCH/DELETE"))
                if not path:
                    issues.append(_issue("P011", "error", "路由缺少 path", ""))
                elif path.startswith("/") or path.startswith("api/"):
                    issues.append(_issue("P011", "error",
                                         f"路由 `{path}` 必须是**相对**路径，不得写 `/api/...`",
                                         f"改写为 `{path.lstrip('/').removeprefix('api/')}`；内核会挂到 `/api/plugins/{pid or '<id>'}/` 下"))

    # P012 · mcp_tools：裸名，前缀由内核加（避免插件自称 p_x__y 撞名）
    tools = manifest.get("mcp_tools")
    if tools is not None:
        if not isinstance(tools, list):
            issues.append(_issue("P012", "error", "mcp_tools 必须是数组", ""))
        else:
            for name in tools:
                text = str(name)
                if text.startswith("p_") or "__" in text:
                    issues.append(_issue("P012", "error",
                                         f"工具名 `{text}` 带前缀：前缀由内核统一加",
                                         f"只写裸名（如 `forecast`），对外名会是 `p_{pid or '<id>'}__{text}`"))
                elif not TOOL_RE.match(text):
                    issues.append(_issue("P012", "error", f"工具名 `{text}` 不合法", "小写字母开头，只含小写字母/数字/下划线"))

    # P013 · settings_schema
    schema = manifest.get("settings_schema")
    if schema is not None and not isinstance(schema, dict):
        issues.append(_issue("P013", "error", "settings_schema 必须是对象（JSON Schema）", ""))

    # P014 · requires.plugins
    requires = manifest.get("requires")
    if requires is not None:
        if not isinstance(requires, dict):
            issues.append(_issue("P014", "error", "requires 必须是对象", '如 `{"plugins":[{"id":"literature-base"}]}`'))
        else:
            deps = requires.get("plugins")
            if deps is not None and not isinstance(deps, list):
                issues.append(_issue("P014", "error", "requires.plugins 必须是数组", ""))
            elif isinstance(deps, list):
                seen = set()
                for dep in deps:
                    dep_id = str((dep or {}).get("id") if isinstance(dep, dict) else dep or "").strip()
                    if not dep_id:
                        issues.append(_issue("P014", "error", "依赖项缺少 id", ""))
                        continue
                    if dep_id == pid:
                        issues.append(_issue("P014", "error", f"插件依赖了自己（{dep_id}）", "去掉该依赖"))
                    if dep_id in seen:
                        issues.append(_issue("P014", "warn", f"依赖 `{dep_id}` 重复声明", "去重"))
                    seen.add(dep_id)

    # P015 · storage.derived_db 只允许 System/Cache/<id>.sqlite
    storage = manifest.get("storage")
    if isinstance(storage, dict) and storage.get("derived_db"):
        raw = str(storage["derived_db"]).replace("\\", "/").strip("/")
        expected = f"System/Cache/{pid}.sqlite"
        if raw != expected:
            issues.append(_issue("P015", "error",
                                 f"storage.derived_db 必须恰好是 `{expected}`，当前 `{raw}`",
                                 "插件自有派生库只允许放在 System/Cache/<id>.sqlite"))

    # P016 · nav[].mount 必须是插件目录内的相对路径且文件存在
    nav = manifest.get("nav")
    if nav is not None:
        if not isinstance(nav, list):
            issues.append(_issue("P016", "error", "nav 必须是数组", ""))
        else:
            for item in nav:
                if not isinstance(item, dict):
                    issues.append(_issue("P016", "error", "nav 每项必须是对象", '如 `{"id":"weather","label":"天气","mount":"web/panel.js"}`'))
                    continue
                mount = str(item.get("mount") or "").strip()
                if not mount:
                    issues.append(_issue("P016", "error", "nav 项缺少 mount", "指向面板脚本，如 `web/panel.js`"))
                    continue
                if Path(mount).is_absolute() or ".." in Path(mount).parts:
                    issues.append(_issue("P016", "error", f"nav.mount `{mount}` 必须是插件目录内的相对路径", ""))
                elif plugin_dir is not None and not (Path(plugin_dir) / mount).is_file():
                    issues.append(_issue("P016", "error", f"nav.mount 指向的文件不存在：{mount}", ""))
                # P019 · slot：槽位面板（不走导航，画进内核给的槽位）
                slot = str(item.get("slot") or "").strip()
                if slot and slot not in KNOWN_SLOTS:
                    issues.append(_issue("P019", "error", f"nav.slot `{slot}` 不是已知槽位",
                                         "当前支持：" + " / ".join(sorted(KNOWN_SLOTS))))

    # P017 · ui:panel 权限与 nav 声明要一致（声明面板却不要 ui:panel 权限，多半是漏了）
    if isinstance(nav, list) and nav and "ui:panel" not in [str(p) for p in (permissions or [])]:
        issues.append(_issue("P017", "warn", "声明了 nav 面板但未申请 ui:panel 权限",
                             "把 `ui:panel` 加入 permissions，便于安装时向用户展示"))

    # P020 · panel：**没有导航页**的 UI（例如只往阅读区/设置页贡献 tab，或只是槽位组件）。
    #       宿主按这个字段加载面板脚本；它与 nav[] 可并存，也可以单独存在。
    panel = manifest.get("panel")
    if panel is not None:
        if not isinstance(panel, dict):
            issues.append(_issue("P020", "error", "panel 必须是对象",
                                 '如 `{"mount":"web/panel.js","style":"web/panel.css"}`'))
        else:
            pmount = str(panel.get("mount") or "").strip()
            if not pmount:
                issues.append(_issue("P020", "error", "panel 缺少 mount", "指向面板脚本，如 `web/panel.js`"))
            elif Path(pmount).is_absolute() or ".." in Path(pmount).parts:
                issues.append(_issue("P020", "error", f"panel.mount `{pmount}` 必须是插件目录内的相对路径", ""))
            elif plugin_dir is not None and not (Path(plugin_dir) / pmount).is_file():
                issues.append(_issue("P020", "error", f"panel.mount 指向的文件不存在：{pmount}", ""))
            pstyle = str(panel.get("style") or "").strip()
            if pstyle:
                if Path(pstyle).is_absolute() or ".." in Path(pstyle).parts:
                    issues.append(_issue("P020", "error", f"panel.style `{pstyle}` 必须是插件目录内的相对路径", ""))
                elif plugin_dir is not None and not (Path(plugin_dir) / pstyle).is_file():
                    issues.append(_issue("P020", "error", f"panel.style 指向的文件不存在：{pstyle}", ""))
            if "ui:panel" not in [str(p) for p in (permissions or [])]:
                issues.append(_issue("P017", "warn", "声明了 panel 但未申请 ui:panel 权限",
                                     "把 `ui:panel` 加入 permissions，便于安装时向用户展示"))

    # P021 · jobs：声明式清单（真正生效的是 register 里的 `ctx.jobs.add(...)`，见 §6.2）
    job_list = manifest.get("jobs")
    if job_list is not None:
        if not isinstance(job_list, list):
            issues.append(_issue("P021", "error", "jobs 必须是数组",
                                 '如 `[{"id":"refresh","interval_min":30}]`'))
        else:
            seen_jobs: set[str] = set()
            for item in job_list:
                if not isinstance(item, dict):
                    issues.append(_issue("P021", "error", "jobs 每项必须是对象", '如 `{"id":"refresh","interval_min":30}`'))
                    continue
                jid = str(item.get("id") or "").strip()
                if not jid:
                    issues.append(_issue("P021", "error", "jobs 项缺少 id", "给任务起一个短名，便于在设置页显示"))
                elif not TOOL_RE.match(jid):
                    issues.append(_issue("P021", "error", f"任务名 `{jid}` 不合法",
                                         "小写字母开头，只含小写字母/数字/下划线"))
                elif jid in seen_jobs:
                    issues.append(_issue("P021", "error", f"任务名 `{jid}` 重复", ""))
                else:
                    seen_jobs.add(jid)
                if "interval_min" in item:
                    try:
                        minutes = float(item.get("interval_min"))
                    except (TypeError, ValueError):
                        issues.append(_issue("P021", "error",
                                             f"任务 `{jid}` 的 interval_min 必须是数字", "单位是分钟，如 30"))
                    else:
                        if minutes <= 0:
                            issues.append(_issue("P021", "error",
                                                 f"任务 `{jid}` 的 interval_min 必须 > 0（收到 {item.get('interval_min')!r}）",
                                                 "最小 1 分钟"))

    # P022 · preview：插件设置页的「演示预览」（可选；只做形状校验，缺图给 warn 不拒载）
    preview = manifest.get("preview")
    if preview is not None:
        if not isinstance(preview, dict):
            issues.append(_issue("P022", "warn", "preview 必须是对象",
                                 '如 `{"summary":"一句话","features":["能做A","能做B"],"screens":["web/preview.png"]}`'))
        else:
            if "summary" in preview and not isinstance(preview.get("summary"), str):
                issues.append(_issue("P022", "warn", "preview.summary 必须是字符串", "一两句话说明这个插件解决什么问题"))
            features = preview.get("features")
            if features is not None and not isinstance(features, list):
                issues.append(_issue("P022", "warn", "preview.features 必须是数组", '如 `["功能点 1","功能点 2"]`'))
            elif isinstance(features, list):
                bad = [f for f in features if not isinstance(f, str)]
                if bad:
                    issues.append(_issue("P022", "warn", "preview.features 每项必须是字符串", str(bad[:3])))
            where = preview.get("where")
            if where is not None and not isinstance(where, str):
                issues.append(_issue("P022", "warn", "preview.where 必须是字符串", "写清在哪里能找到它，如「侧栏 → 指标表」"))
            screens = preview.get("screens")
            if screens is not None and not isinstance(screens, list):
                issues.append(_issue("P022", "warn", "preview.screens 必须是数组", '如 `["web/preview.png"]`'))
            elif isinstance(screens, list):
                for shot in screens:
                    rel = str(shot or "").strip()
                    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
                        issues.append(_issue("P022", "warn", f"preview.screens `{shot}` 必须是插件目录内的相对路径", ""))
                    elif plugin_dir is not None and not (Path(plugin_dir) / rel).is_file():
                        issues.append(_issue("P022", "warn", f"preview.screens 指向的图片不存在：{rel}",
                                             "把截图放进插件目录（如 web/preview.png）"))

    return issues


def errors(issues: list[dict[str, str]]) -> list[dict[str, str]]:
    return [i for i in issues if i.get("level") == "error"]


def summarize(issues: list[dict[str, str]]) -> str:
    return "；".join(f"{i['code']} {i['message']}" for i in errors(issues))
