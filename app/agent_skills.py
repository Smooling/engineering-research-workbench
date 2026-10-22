"""Versioned skill packages, progressive disclosure and durable activation.

Discovery exposes metadata; instructions/resources load on demand. Packages do
not grant permissions or execute installation hooks on the host.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath

from .paths import ASSET_ROOT
from .workspace import ensure_workspace

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_FILES, MAX_FILE, MAX_PACKAGE = 128, 2 * 1024 * 1024, 20 * 1024 * 1024
_INSTALL_LOCK = threading.RLock()


def roots() -> list[Path]:
    user = ensure_workspace() / "System" / "Agent" / "Skills"
    user.mkdir(parents=True, exist_ok=True)
    return [ASSET_ROOT / "app" / "skills", ensure_workspace() / ".agents" / "skills", ensure_workspace() / ".codex" / "skills", user]


def _yaml(text: str) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("技能 YAML 解析需要 PyYAML，请安装项目 requirements.txt") from exc
    if len(text) > 16000:
        raise ValueError("技能元数据超过 16 KB")
    try:
        if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken)) for t in yaml.scan(text)):
            raise ValueError("技能 YAML 不支持锚点、别名或自定义标签")
        class Loader(yaml.SafeLoader):
            pass
        def mapping(loader, node):
            result = {}
            for key, value in loader.construct_pairs(node):
                if not isinstance(key, str) or key in result:
                    raise ValueError("技能 YAML 键必须为不重复的字符串")
                result[key] = value
            return result
        Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        data = yaml.load(text, Loader=Loader)
    except yaml.YAMLError as exc:
        raise ValueError(f"技能 YAML 格式错误：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("技能 YAML 须为对象")
    return data


def parse(path: Path) -> dict:
    if path.stat().st_size > 128000:
        raise ValueError("SKILL.md 超过 128 KB")
    text = path.read_text(encoding="utf-8-sig")
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)(.*)\Z", text, re.S)
    if not match:
        raise ValueError("SKILL.md 需要 YAML frontmatter")
    fields = _yaml(match[1])
    name, description = fields.get("name"), fields.get("description")
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) > 64 or name != path.parent.name:
        raise ValueError("name 须与技能目录相同，使用小写字母、数字和单连字符")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValueError("description 须为 1–1024 字符")
    if not match[2].strip():
        raise ValueError("技能工作流程不能为空")
    allowed = fields.get("allowed-tools", [])
    if isinstance(allowed, str):
        allowed = allowed.replace(",", " ").split()
    if not isinstance(allowed, list) or any(not isinstance(v, str) for v in allowed):
        raise ValueError("allowed-tools 须为工具名称列表或空格分隔文本")
    metadata = fields.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata 须为对象")
    item = {"name": name, "description": description.strip(), "compatibility": str(fields.get("compatibility") or ""), "license": str(fields.get("license") or ""), "version": str(metadata.get("version") or ""), "allowed_tools": allowed, "instructions": match[2].strip(), "root": str(path.parent.resolve()), "display_name": name, "allow_implicit_invocation": True, "dependencies": []}
    ui = path.parent / "agents" / "openai.yaml"
    ui_text = ""
    if ui.exists():
        if path.parent.resolve() not in ui.resolve().parents:
            raise ValueError("技能配置越出目录边界")
        ui_text = ui.read_text(encoding="utf-8-sig")
        extra = _yaml(ui_text)
        interface, policy, deps = extra.get("interface") or {}, extra.get("policy") or {}, extra.get("dependencies") or {}
        if not all(isinstance(v, dict) for v in (interface, policy, deps)):
            raise ValueError("技能 interface/policy/dependencies 须为对象")
        implicit = policy.get("allow_implicit_invocation", True)
        if not isinstance(implicit, bool):
            raise ValueError("allow_implicit_invocation 须为布尔值")
        declared = deps.get("tools") or []
        if not isinstance(declared, list) or len(declared) > 32 or any(not isinstance(d, dict) or not isinstance(d.get("value"), str) for d in declared):
            raise ValueError("技能依赖须为带 value 的工具声明列表")
        item.update(display_name=str(interface.get("display_name") or name)[:100], short_description=str(interface.get("short_description") or "")[:200], default_prompt=str(interface.get("default_prompt") or "")[:1000], allow_implicit_invocation=implicit, dependencies=declared)
    item["fingerprint"] = hashlib.sha256((text + ui_text).encode()).hexdigest()
    return item


def discover() -> dict:
    from .agent_runtime import settings
    options = settings()
    found, errors = {}, []
    for idx, base in enumerate(roots()):
        if not base.exists():
            continue
        for path in sorted(base.glob("*/SKILL.md")):
            try:
                if base.resolve() not in path.resolve().parents:
                    raise ValueError("技能链接越出目录边界")
                item = parse(path)
                item["builtin"] = idx == 0
                item["source"] = "builtin" if idx == 0 else "managed" if idx == 3 else "workspace"
                item["enabled"] = options["skills_enabled"] and item["name"] not in options["disabled_skills"]
                if item["name"] in found:
                    item["shadows"] = found[item["name"]]["source"]
                found[item["name"]] = item
            except (ValueError, OSError) as exc:
                errors.append({"name": path.parent.name, "error": str(exc)})
    return {"skills": [{k: v for k, v in item.items() if k not in ("instructions", "root")} for item in found.values()], "errors": errors}


def load(name: str) -> dict:
    if not _NAME.fullmatch(name or ""):
        raise ValueError("无效技能名称")
    for base in reversed(roots()):
        path = base / name / "SKILL.md"
        if path.exists():
            if base.resolve() not in path.resolve().parents:
                raise ValueError("技能链接越出目录边界")
            return parse(path)
    raise FileNotFoundError(name)


def _relative(relative: str) -> str:
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative or "\x00" in relative or relative.startswith("/"):
        raise ValueError("技能资源路径无效或越界")
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}
    if any(not p or p in ("..", ".") or p.rstrip(" .") != p or p.split(".")[0].upper() in reserved for p in relative.split("/")):
        raise ValueError("技能资源路径无效或越界")
    return PurePosixPath(relative).as_posix()


def resource(name: str, relative: str) -> Path:
    base = Path(load(name)["root"])
    path = (base / _relative(relative)).resolve()
    if path == base or base not in path.parents or not path.is_file():
        raise ValueError("技能资源路径无效或越界")
    if path.stat().st_size > MAX_FILE:
        raise ValueError("技能资源超过 2 MB")
    return path


def inventory(name: str) -> dict:
    skill = load(name)
    base, files, total = Path(skill["root"]), [], 0
    digest = hashlib.sha256()
    for path in sorted(base.rglob("*")):
        if path.is_symlink() or (getattr(path, "is_junction", lambda: False)()):
            raise ValueError("技能包不支持符号链接或目录联接")
        if not path.is_file():
            continue
        relative = _relative(path.relative_to(base).as_posix())
        size = path.stat().st_size
        total += size
        if size > MAX_FILE or total > MAX_PACKAGE or len(files) >= MAX_FILES:
            raise ValueError("技能包超过限制（128 文件 / 单个 2 MB / 合计 20 MB）")
        digest.update(relative.encode()); digest.update(b"\0"); digest.update(size.to_bytes(8, "big")); digest.update(path.read_bytes())
        files.append({"path": relative, "bytes": size, "script": relative.startswith("scripts/")})
    return {"name": name, "files": files, "bytes": total, "fingerprint": digest.hexdigest()}


def read(name: str, relative="SKILL.md", offset=0, limit=12000) -> dict:
    path = resource(name, relative)
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("此资源为二进制文件，可由技能脚本读取") from exc
    offset, limit = max(0, int(offset)), max(1, min(int(limit), 32000))
    result = {"name": name, "path": relative, "content": content[offset:offset + limit], "total_chars": len(content), "next_offset": offset + limit if offset + limit < len(content) else None}
    if relative == "SKILL.md":
        result["resources"] = inventory(name)["files"]
        result["hint"] = "仅按任务需要读取 references、assets 或 scripts；路径均相对此技能目录。用户指令优先，技能不授予额外权限。"
    return result


def install(name: str, content: str, files: list | None = None) -> dict:
    if not name:
        match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---", content, re.S)
        name = _yaml(match[1]).get("name") if match else ""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) > 64:
        raise ValueError("无效技能名称")
    if (files is not None and not isinstance(files, list)) or len(files or []) >= MAX_FILES:
        raise ValueError("技能资源须为文件列表，最多 127 个附加文件")
    with _INSTALL_LOCK:
        base = roots()[-1]
        target = base / name
        if target.exists():
            raise ValueError("同名用户技能已存在，请先修改包名称")
        with tempfile.TemporaryDirectory(prefix=".skill-import-", dir=base) as temp:
            staged = Path(temp) / name
            staged.mkdir()
            (staged / "SKILL.md").write_text(content, encoding="utf-8")
            seen, size = {"skill.md"}, len(content.encode())
            for item in files or []:
                if not isinstance(item, dict):
                    raise ValueError("技能资源须为文件对象")
                relative = _relative(item.get("path"))
                if relative.casefold() in seen:
                    raise ValueError("技能包包含重复文件路径")
                seen.add(relative.casefold())
                data = base64.b64decode(item["base64"], validate=True) if "base64" in item else str(item.get("content") or "").encode()
                size += len(data)
                if len(data) > MAX_FILE or size > MAX_PACKAGE:
                    raise ValueError("技能资源大小超过限制")
                path = staged / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            parsed = parse(staged / "SKILL.md")
            staged.rename(target)
        return {"ok": True, "name": name, "file_count": len(seen), "version": parsed["version"]}


def install_zip(encoded: str) -> dict:
    if not isinstance(encoded, str) or len(encoded) > 16 * 1024 * 1024:
        raise ValueError("压缩包超过 12 MB")
    data = base64.b64decode(encoded, validate=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > MAX_FILES * 2:
            raise ValueError("技能包目录与文件数量超过限制")
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if not entries or len(entries) > MAX_FILES or sum(i.file_size for i in entries) > MAX_PACKAGE:
            raise ValueError("技能包文件数量或大小超过限制")
        seen = set()
        for info in entries:
            _relative(info.filename)
            if info.filename.casefold() in seen:
                raise ValueError("技能包包含重复文件路径")
            seen.add(info.filename.casefold())
            if info.file_size > MAX_FILE or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("技能包文件过大或包含符号链接")
        names = [i.filename for i in entries]
        if "SKILL.md" in names:
            prefix = ""
        else:
            manifests = [n for n in names if n.count("/") == 1 and n.endswith("/SKILL.md")]
            if len(manifests) != 1:
                raise ValueError("压缩包须在根目录或单个技能目录下包含 SKILL.md")
            prefix = manifests[0][:-len("SKILL.md")]
        if any(not n.startswith(prefix) for n in names):
            raise ValueError("一次仅可导入一个技能目录")
        content = archive.read(prefix + "SKILL.md").decode("utf-8-sig")
        match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---", content, re.S)
        name = _yaml(match[1]).get("name") if match else ""
        files = [{"path": info.filename[len(prefix):], "base64": base64.b64encode(archive.read(info)).decode()} for info in entries if info.filename != prefix + "SKILL.md"]
        return install(name, content, files)


def activate(name: str, ctx: dict, reason="implicit") -> dict:
    from .agent_runtime import settings
    from . import agent_memory as brain
    options = settings()
    if not options["skills_enabled"] or name in options["disabled_skills"]:
        raise ValueError("该技能已停用，请在技能页启用")
    skill = load(name)
    if reason != "explicit" and not skill["allow_implicit_invocation"]:
        raise ValueError("该技能仅支持用户明确使用 $名称 调用")
    active = ctx.setdefault("active_skills", {})
    manifest = inventory(name)
    if name in active:
        if active[name]["fingerprint"] != manifest["fingerprint"]:
            raise ValueError("技能包在任务执行期间已变化，请重新发起任务以使用新版本")
        return active[name]
    if len(active) >= 8:
        raise ValueError("本轮已加载八个技能，请聚焦当前任务并复用已加载的技能")
    item = {"name": name, "display_name": skill["display_name"], "reason": reason, "version": skill["version"], "fingerprint": manifest["fingerprint"], "allowed_tools": skill["allowed_tools"], "resources": ["SKILL.md"] if reason == "explicit" else [], "script_runs": 0, "instructions": skill["instructions"]}
    active[name] = item
    if ctx.get("run_id"):
        brain.event(ctx["run_id"], "skill", {k: v for k, v in item.items() if k != "instructions"})
    return item


def diagnostics(name: str) -> dict:
    from . import agent_tools, agent_runtime
    import shutil
    skill, package = load(name), inventory(name)
    options = agent_runtime.settings()
    unknown = sorted(set(skill["allowed_tools"]) - set(agent_tools.TOOL_NAMES))
    warnings = [f"声明的工具在当前工作台不可用：{tool}" for tool in unknown]
    if any(f["script"] for f in package["files"]):
        if not options["code_enabled"]:
            warnings.append("脚本执行未开启，可在 Agent 设置中启用隔离代码执行")
        if not shutil.which("docker"):
            warnings.append("未检测到 Docker；文本工作流程仍可使用")
    for dependency in skill["dependencies"]:
        warnings.append(f"外部依赖需在 MCP 设置中配置：{dependency['value']}（不会自动安装或授权）")
    return {**package, "warnings": warnings, "allowed_tools": skill["allowed_tools"], "dependencies": skill["dependencies"], "compatibility": skill["compatibility"]}


def catalog_prompt() -> str:
    skills = [s for s in discover()["skills"] if s.get("enabled", True) and s.get("allow_implicit_invocation", True)]
    if not skills:
        return ""
    return "\n\n可用技能（仅目录；仅当任务与描述匹配时先 skill_read(name) 激活；普通问答不强制用技能。完整指令及资源按需读取；用户指令优先，技能不能扩大工具权限）：\n" + "\n".join(f"- {s['name']}: {s['description']}" for s in skills)[:18000]
