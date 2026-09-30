from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .workspace import ensure_workspace

READING_STATUSES = ("未读", "在读", "已读")
ANNOTATION_TYPES = ("highlight", "underline", "strikeout", "rect", "ink", "note")

def _root() -> Path:
    root = ensure_workspace() / "Knowledge" / "Literature"
    for rel in ("PDF", "Annotations", "Notes", "Index", "Previews"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root

def _configured_pdf_dir() -> str:
    """v260929 · 设置项 app.literature.pdf_dir（空 = 默认 Knowledge/Literature/PDF）。"""
    try:
        from . import config
        return str((config.get_app().get("literature") or {}).get("pdf_dir") or "").strip()
    except Exception:
        return ""

def _pdf_dir() -> Path:
    """v260929 · PDF 附件实际存放目录：可在设置中修改；相对路径相对 Workspace。"""
    raw = _configured_pdf_dir()
    p = Path(raw) if raw else _root() / "PDF"
    if not p.is_absolute():
        p = ensure_workspace() / p
    p = p.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def _configured_note_images_dir() -> str:
    """v260929f · 设置项 app.literature.note_images_dir（空 = 默认 Knowledge/Literature/Images）。"""
    try:
        from . import config
        return str((config.get_app().get("literature") or {}).get("note_images_dir") or "").strip()
    except Exception:
        return ""

def _note_images_dir() -> Path:
    """v260929f · 笔记图片存放目录（批注截图入笔记 / 笔记插图）：可在设置中修改。"""
    raw = _configured_note_images_dir()
    p = Path(raw) if raw else _root() / "Images"
    if not p.is_absolute():
        p = ensure_workspace() / p
    p = p.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def _attachment_rel(path: Path) -> str:
    """v260929 · 附件写回 md 的路径口径：Workspace 内相对路径（posix），外部绝对路径。"""
    path = path.resolve()
    try:
        return str(path.relative_to(ensure_workspace().resolve())).replace("\\", "/")
    except Exception:
        return str(path)

def _registry_path() -> Path:
    return _root() / "Index" / "library.json"

def _load_registry() -> dict[str, Any]:
    p = _registry_path()
    if not p.exists():
        return {"version": 1, "items": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict): raise ValueError()
        data.setdefault("items", [])
        return data
    except Exception:
        return {"version": 1, "items": []}

def _save_registry(data: dict[str, Any]) -> None:
    p = _registry_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)

def _safe_name(name: str) -> str:
    base = Path(str(name or "paper.pdf")).name
    stem = re.sub(r"[^\w\-. ()\[\]]+", "_", Path(base).stem, flags=re.UNICODE).strip(" ._")[:120] or "paper"
    return stem + ".pdf"

def list_items(query: str = "", status: str = "", category: str = "", page: int = 1, page_size: int = 60, mark: str = "") -> dict[str, Any]:
    rows = list(_load_registry().get("items") or [])
    _join_doc_meta_batch(rows)  # v260929 · 批量归一 md 真值后再过滤/排序，保证检索与展示口径一致
    q = str(query or "").strip().lower()
    if q:
        rows = [x for x in rows if q in " ".join([
            str(x.get("title") or ""), str(x.get("authors") or ""), str(x.get("venue") or ""),
            " ".join(x.get("tags") or []), " ".join(x.get("categories") or [])
        ]).lower()]
    if status:
        rows = [x for x in rows if x.get("reading_status") == status]
    if category:
        rows = [x for x in rows if category in (x.get("categories") or [])]
    if mark:  # v260929 · 分类标记筛选（与文献列表页口径一致：分类即 kind_marks）
        rows = [x for x in rows if mark in (x.get("kind_marks") or [])]
    rows.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    total = len(rows)
    page = max(1, int(page)); page_size = max(10, min(200, int(page_size)))
    start = (page - 1) * page_size
    return {"items": rows[start:start+page_size], "total": total, "page": page, "page_size": page_size}

_DOC_META_KEYS = ("title", "authors", "year", "venue", "doi", "url", "cite_key", "bibtex")

def _apply_doc_meta(item: dict[str, Any], doc: dict[str, Any]) -> None:
    """v260929 · 用 md doc 的元数据覆盖 library 字段（真值归一的公共覆盖逻辑）。"""
    for key in _DOC_META_KEYS:
        val = doc.get(key)
        if val:
            item[key] = val
    if doc.get("tags"):
        item["tags"] = doc["tags"]
    if doc.get("projects"):
        item["projects"] = doc["projects"]
    if doc.get("excerpt"):  # v260929 · 摘要仅供列表展示（与文献列表页同源同款），不回写
        item["excerpt"] = doc["excerpt"]
    if doc.get("kind_marks"):  # v260929 · 分类标记徽章（阅读区与列表页同源，取自 md 真值）
        item["kind_marks"] = doc["kind_marks"]

def _join_doc_meta_batch(rows: list[dict[str, Any]]) -> None:
    """v260929 · 列表批量归一：一次批量取 doc（每篇文献只读一次盘），替代逐条 get_doc 的
    O(N×M) 全库扫描——此前文献多时进入 PDF 工作区加载极慢的根因。"""
    ids = [str(r.get("doc_id") or "") for r in rows if r.get("doc_id")]
    if not ids:
        return
    try:
        from . import store
        docs = store.get_docs_by_ids(ids)
    except Exception:
        return
    for r in rows:
        doc = docs.get(str(r.get("doc_id") or ""))
        if doc:
            _apply_doc_meta(r, doc)

def _join_doc_meta(item: dict[str, Any]) -> dict[str, Any]:
    """v260929 · 真值归一（阶段 3）：输出前用关联 md 条目的元数据覆盖 library 字段。
    md 是唯一真值——用户在编辑器里改的题名/作者/DOI/BibTeX 即时生效于工作区展示与检索；
    md 读取失败（条目已删/未建）时静默退回 library 自身值，保证工作区不因缺 md 而不可用。"""
    doc_id = str(item.get("doc_id") or "")
    if not doc_id:
        return item
    try:
        from . import store
        doc = store.get_doc(doc_id)
        _apply_doc_meta(item, doc)
    except Exception:
        pass
    return item

def get_item(paper_id: str) -> dict[str, Any]:
    for item in _load_registry().get("items") or []:
        if item.get("id") == paper_id:
            return _join_doc_meta(dict(item))
    raise FileNotFoundError(paper_id)

_MD_SYNC_KEYS = {"title", "authors", "year", "venue", "doi", "url", "cite_key", "bibtex", "tags", "projects", "kind_marks"}  # v260929 · 分类标记同样以 md 为真值

def update_item(paper_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    data = _load_registry()
    allowed = {"title","authors","year","venue","doi","url","cite_key","bibtex","reading_status","categories","tags","projects","favorite","last_page","page_count","kind_marks"}
    for item in data.get("items") or []:
        if item.get("id") != paper_id: continue
        md_patch: dict[str, Any] = {}
        for key in allowed:
            if key in patch:
                value = patch[key]
                if key == "reading_status" and value not in READING_STATUSES: value = "未读"
                if key in {"categories","tags","projects"}:
                    value = list(dict.fromkeys(str(v).strip() for v in (value or []) if str(v).strip()))
                item[key] = value
                if key in _MD_SYNC_KEYS: md_patch[key] = value  # v260929 · 元数据改动需同步回 md（真值）
        item["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _save_registry(data)
        doc_id = str(item.get("doc_id") or "")
        if doc_id and md_patch:  # v260929 · 工作区改元数据 → 经 indexer.update_doc 同步 md 并刷新索引，两处口径一致
            try:
                from . import indexer
                indexer.update_doc(doc_id, md_patch)
            except Exception:
                pass
        return _join_doc_meta(dict(item))
    raise FileNotFoundError(paper_id)

def delete_item(paper_id: str) -> dict[str, Any]:
    data = _load_registry()
    item = next((x for x in data.get("items") or [] if x.get("id") == paper_id), None)
    if not item: raise FileNotFoundError(paper_id)
    doc_id = str(item.get("doc_id") or "")  # v260929 · 删除前留存关联，供联动清理 md 条目
    pdf = (_pdf_dir() / str(item.get("stored_filename") or "")).resolve()
    data["items"] = [x for x in data["items"] if x.get("id") != paper_id]
    trash = ensure_workspace() / "System" / "Trash" / "Literature"
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for p in (pdf, annotation_path(paper_id), note_path(paper_id), _root() / "Previews" / paper_id):
        if p.exists(): shutil.move(str(p), str(trash / f"{stamp}-{p.name}"))
    _save_registry(data)
    if doc_id:  # v260929 · 联动：关联 md 条目经 indexer.delete_doc 一并移入 Trash 并清索引行，避免孤儿条目
        try:
            from . import indexer
            indexer.delete_doc(doc_id)
        except Exception:
            pass
    return {"ok": True}

def import_pdf(filename: str, source_path: Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = metadata or {}
    paper_id = uuid.uuid4().hex
    name = _safe_name(filename)
    dest = _pdf_dir() / f"{paper_id}-{name}"
    h = hashlib.sha256()
    with source_path.open("rb") as src, dest.open("wb") as out:
        head = src.read(5)
        if head != b"%PDF-": raise ValueError("仅支持有效 PDF 文件")
        h.update(head); out.write(head)
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk: break
            h.update(chunk); out.write(chunk)
    now = datetime.now().isoformat(timespec="seconds")
    item = {
        "id": paper_id, "title": str(metadata.get("title") or Path(name).stem),
        "authors": str(metadata.get("authors") or ""), "year": str(metadata.get("year") or ""),
        "venue": str(metadata.get("venue") or ""), "doi": str(metadata.get("doi") or ""),
        "url": str(metadata.get("url") or ""), "cite_key": str(metadata.get("cite_key") or ""),
        "bibtex": str(metadata.get("bibtex") or ""), "reading_status": "未读",
        "categories": [], "tags": [], "projects": [], "favorite": False,
        "filename": name, "stored_filename": dest.name, "size": dest.stat().st_size,
        "sha256": h.hexdigest(), "last_page": 1, "page_count": 0,
        "created_at": now, "updated_at": now,
    }
    data = _load_registry(); data["items"].append(item); _save_registry(data)
    _ensure_doc_entry(item)  # v260929 · 数据互认：上传即同步创建 literature md 条目（真值载体，正文即文献笔记）
    return item


def _ensure_doc_entry(item: dict[str, Any]) -> str:
    """v260929 · 数据互认（合并阶段 2）：为 library 条目同步创建 literature md 条目。
    md 是元数据唯一真值载体：attachment 指向工作区 PDF（相对 Workspace 路径），
    cite_key 留空由 store 自动生成；doc_id 回写 library.json 形成双向关联。
    md 创建失败不阻塞上传（doc_id 置空，可由重建端点补齐）。"""
    if item.get("doc_id"):
        return str(item["doc_id"])
    doc_id = ""
    try:
        from . import store, indexer
        doc = store.create_doc("literature", {
            "title": str(item.get("title") or item.get("filename") or "未命名文献"),
            "authors": item.get("authors") or "",
            "year": item.get("year") or "",
            "venue": item.get("venue") or "",
            "doi": item.get("doi") or "",
            "url": item.get("url") or "",
            "cite_key": item.get("cite_key") or "",
            "attachment": _attachment_rel(_pdf_dir() / item["stored_filename"]),
        })
        doc_id = str(doc["id"])
        try:  # v260929 · 直写 md 须补刷 SQLite 索引，否则文献列表页（索引查询）看不到新条目
            indexer.index_doc_path(str(doc.get("path") or ""))
        except Exception:
            pass
        data = _load_registry()
        for x in data.get("items") or []:
            if x.get("id") == item.get("id"):
                x["doc_id"] = doc_id
        _save_registry(data)
    except Exception:
        doc_id = ""
    return doc_id


def rebuild_registry(doc_id: str = "") -> dict[str, Any]:
    """v260929 · 真值归一重建（阶段 3）：以文献 md 条目为唯一真值修复 library.json，幂等可重复执行。
    a) md.attachment 尾段名与库内 stored_filename 匹配 → 回填 doc_id 双向关联（link）
    b) md.attachment 指向有效 PDF 但库内未登记 → PDF 迁入 Knowledge/Literature/PDF/ 统一存放并登记
       新条目（元数据取自 md frontmatter），md.attachment 同步更新为库内路径（register）；
       Workspace 内的附件原地移动（合并存放空间、不留双份），Workspace 外绝对路径仅复制（不破坏外部文件）
    c) 库中 doc_id 为空的孤儿条目 → 经 _ensure_doc_entry 补建 md（ensure，仅全量模式）
    doc_id 传入时仅处理该条目（附件徽章点击的自动登记路径），返回值附处理后的 attachment。"""
    from . import store
    data = _load_registry()
    items = data.setdefault("items", [])
    stats = {"linked": 0, "registered": 0, "ensured": 0}
    single = bool(doc_id)
    docs = [d for d in store.list_docs("literature") if not single or d["id"] == doc_id]
    result_att = ""
    for doc in docs:
        att = str(doc.get("attachment") or "").strip()
        if not att:
            continue
        name = att.replace("\\", "/").split("/")[-1]
        hit = next((x for x in items if str(x.get("stored_filename") or "") == name), None)
        if hit is not None:
            if not hit.get("doc_id"):
                hit["doc_id"] = doc["id"]
                stats["linked"] += 1
            result_att = att
            continue
        src = store.resolve_attachment(doc)
        if src is None:
            continue
        paper_id = uuid.uuid4().hex
        safe = _safe_name(src.name)
        dest = _pdf_dir() / f"{paper_id}-{safe}"
        if src.resolve() != dest.resolve():
            in_ws = False  # v260929 · 合并存放空间：Workspace 内移动迁入，外部绝对路径复制保原件
            try:
                in_ws = src.resolve().is_relative_to(ensure_workspace().resolve())
            except Exception:
                pass
            (shutil.move if in_ws else shutil.copy2)(str(src), str(dest))
        h = hashlib.sha256()
        with dest.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            bibtex = str(store.get_doc(doc["id"]).get("bibtex") or "")
        except Exception:
            bibtex = ""
        items.append({
            "id": paper_id, "title": str(doc.get("title") or Path(safe).stem),
            "authors": str(doc.get("authors") or ""), "year": str(doc.get("year") or ""),
            "venue": str(doc.get("venue") or ""), "doi": str(doc.get("doi") or ""),
            "url": str(doc.get("url") or ""), "cite_key": str(doc.get("cite_key") or ""),
            "bibtex": bibtex, "reading_status": "未读",
            "categories": [], "tags": list(doc.get("tags") or []),
            "projects": list(doc.get("projects") or []), "favorite": False,
            "filename": safe, "stored_filename": dest.name,
            "size": dest.stat().st_size, "sha256": h.hexdigest(),
            "last_page": 1, "page_count": 0, "doc_id": doc["id"],
            "created_at": now, "updated_at": now,
        })
        stats["registered"] += 1
        rel = _attachment_rel(dest)
        result_att = rel  # 单条模式：登记后的库内路径，返回给前端重试跳转
        if att.replace("\\", "/") != rel:
            try:  # v260929 · attachment 更新走 store（indexer 白名单无此键），随后补刷该行索引
                upd = store.update_doc(doc["id"], {"attachment": rel})
                from . import indexer
                indexer.index_doc_path(str(upd.get("path") or ""))
            except Exception:
                pass
    if not single:  # 孤儿补建仅全量模式执行（单条登记无需扫全库）
        for x in list(items):
            if not x.get("doc_id"):
                did = _ensure_doc_entry(x)
                if did:
                    x["doc_id"] = did
                    stats["ensured"] += 1
    _save_registry(data)
    out = {"ok": True, **stats}
    if single: out["attachment"] = result_att
    return out


def storage_info() -> dict[str, Any]:
    """v260929 · 设置页：当前 PDF 存放目录与库内文件概况。"""
    d = _pdf_dir()
    files = [x for x in d.glob("*.pdf") if x.is_file()] if d.is_dir() else []
    ni = _note_images_dir()
    ni_files = [x for x in ni.iterdir() if x.is_file()] if ni.is_dir() else []
    return {
        "pdf_dir": str(d),
        "is_default": not _configured_pdf_dir(),
        "default_dir": str((_root() / "PDF").resolve()),
        "file_count": len(files),
        "total_bytes": sum(x.stat().st_size for x in files),
        # v260929f · 笔记图片目录（批注截图入笔记 / 笔记插图共用）
        "note_images_dir": str(ni),
        "note_images_is_default": not _configured_note_images_dir(),
        "note_images_count": len(ni_files),
    }

def set_pdf_dir(new_dir: str, move_existing: bool = True) -> dict[str, Any]:
    """v260929 · 设置页：修改 PDF 存放目录（app.literature.pdf_dir）。
    move_existing 时把旧目录下现有 PDF 移动到新目录，并回写指向旧目录的文献条目 attachment。
    目录本身不变更 Annotations/Notes/Index/Previews（仍在 Workspace 知识目录内）。"""
    from . import config
    new_dir = str(new_dir or "").strip()
    old = _pdf_dir()
    if new_dir:
        target = Path(new_dir)
        if not target.is_absolute():
            target = ensure_workspace() / target
        target = target.resolve()
        if target.exists() and not target.is_dir():
            raise ValueError("目标路径已存在且不是文件夹")
        if target == old:
            return {"ok": True, "pdf_dir": str(old), "moved": 0, "skipped": 0, "updated": 0}
    else:
        target = (_root() / "PDF").resolve()
        if target == old:
            return {"ok": True, "pdf_dir": str(old), "moved": 0, "skipped": 0, "updated": 0}
    app = config.get_app()
    app.setdefault("literature", {})["pdf_dir"] = new_dir
    config.save_app(app)
    moved = skipped = updated = 0
    if move_existing and old.is_dir() and old != target:
        target.mkdir(parents=True, exist_ok=True)
        for f in old.iterdir():
            if not (f.is_file() and f.suffix.lower() == ".pdf"):
                continue
            dest = target / f.name
            if dest.exists():
                skipped += 1
                continue
            shutil.move(str(f), str(dest))
            moved += 1
    if move_existing:
        try:
            from . import indexer, store
            for doc in store.list_docs("literature"):
                src = store.resolve_attachment(doc)
                if src is None:
                    continue
                try:
                    src.relative_to(old)
                except ValueError:
                    continue  # 不指向旧目录的附件（含外部绝对路径）不动
                dest = target / src.name
                if not dest.exists():
                    continue
                try:
                    upd = store.update_doc(doc["id"], {"attachment": _attachment_rel(dest)})
                    indexer.index_doc_path(str(upd.get("path") or ""))
                    updated += 1
                except Exception:
                    pass
        except Exception:
            pass
    return {"ok": True, "pdf_dir": str(target), "moved": moved, "skipped": skipped, "updated": updated}

def open_folder() -> dict[str, Any]:
    """v260929 · 设置页：在系统文件管理器中打开 PDF 存放目录。"""
    d = _pdf_dir()
    if not d.is_dir():
        raise FileNotFoundError(str(d))
    if os.name == "nt":
        os.startfile(str(d))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(d)])
    else:
        subprocess.Popen(["xdg-open", str(d)])
    return {"ok": True, "pdf_dir": str(d)}

def set_note_images_dir(new_dir: str) -> dict[str, Any]:
    """v260929f · 设置页：修改笔记图片存放目录（app.literature.note_images_dir）。
    仅影响之后上传的图片，不迁移既有文件。"""
    from . import config
    new_dir = str(new_dir or "").strip()
    target = _root() / "Images"
    if new_dir:
        t = Path(new_dir)
        if not t.is_absolute():
            t = ensure_workspace() / t
        t = t.resolve()
        if t.exists() and not t.is_dir():
            raise ValueError("目标路径已存在且不是文件夹")
        target = t
    app = config.get_app()
    app.setdefault("literature", {})["note_images_dir"] = new_dir
    config.save_app(app)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "note_images_dir": str(target)}

def save_note_image(paper_id: str, data_url: str) -> dict[str, Any]:
    """v260929f · 笔记插图 / 批注截图入笔记：把 data_url 图片落盘到笔记图片目录。
    文件名 {paper_id}-{时间戳}-{随机}，避免同名覆盖；返回路径口径与附件一致
    （Workspace 内相对 posix 路径，外部绝对路径）。"""
    paper_id = str(paper_id or "")
    if paper_id:
        get_item(paper_id)  # 校验文献存在；未关联条目也允许插图（paper_id 仅作命名前缀）
    data_url = str(data_url or "")
    m = re.match(r"^data:image/(webp|png|jpeg);base64,(.+)$", data_url, re.I | re.S)
    if not m:
        raise ValueError("仅支持 webp / png / jpeg 图片")
    ext = {"jpeg": "jpg"}.get(m.group(1).lower(), m.group(1).lower())
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception as exc:
        raise ValueError("图片数据无效") from exc
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError("图片超过 10 MB 上限")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{paper_id or 'note'}-{stamp}-{uuid.uuid4().hex[:4]}.{ext}"
    target = _note_images_dir() / name
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(target)
    path = _attachment_rel(target)
    return {"ok": True, "path": path, "filename": name, "in_workspace": not Path(path).is_absolute()}


def copy_preview_to_note_images(paper_id: str, preview_path: str) -> dict[str, Any]:
    """v260929w · 批注截图入笔记：把批注缩略图复制到笔记图片目录（设置指定的位置）。
    原 Previews 缩略图不动（删除批注时会清理它，笔记中的引用须独立存在）。"""
    rel = str(preview_path or "").replace("\\", "/").strip("/")
    if not rel:
        raise ValueError("缺少批注截图路径")
    ws = ensure_workspace().resolve()
    src = (ws / rel).resolve()
    previews = (_root() / "Previews").resolve()
    if previews not in src.parents:
        raise ValueError("仅支持复制批注截图（Previews 目录内）")
    if not src.is_file():
        raise FileNotFoundError("批注截图不存在")
    if src.suffix.lower() not in (".webp", ".png", ".jpg", ".jpeg"):
        raise ValueError("仅支持 webp / png / jpeg 图片")
    paper_id = str(paper_id or "")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{paper_id or 'note'}-{stamp}-{uuid.uuid4().hex[:4]}{src.suffix.lower()}"
    target = _note_images_dir() / name
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(src.read_bytes())
    tmp.replace(target)
    path = _attachment_rel(target)
    return {"ok": True, "path": path, "filename": name, "in_workspace": not Path(path).is_absolute()}


def _cite_key_from(title: str, year: str, authors: str) -> str:
    """v260929 · 自动填写（阶段 4）：firstauthor 姓氏 + 年份生成 cite_key，缺姓氏时退化用题名缩写。"""
    first = str(authors or "").split(";")[0].strip()
    last = ""
    for part in reversed(first.replace(",", " ").split()):
        part = part.strip(".()")
        if part and part.isalpha():
            last = part
            break
    if not last:
        last = "".join(ch for ch in str(title or "") if ch.isascii() and ch.isalpha())[:20]
    key = re.sub(r"[^A-Za-z0-9]+", "", last).lower() + re.sub(r"\D", "", str(year or ""))
    return key or "paper"


def lookup_metadata(identifier: str) -> dict[str, Any]:
    """v260929 · 自动填写（阶段 4）：识别 DOI / arXiv 编号并联网抓取元数据（CrossRef / arXiv API）。
    仅用标准库；识别失败或网络不可达时抛 ValueError，给出可读信息由前端 toast 提示。
    返回字段与文献条目表单一一对应：title/authors/year/venue/doi/url/cite_key。"""
    import urllib.request
    import urllib.parse
    import xml.etree.ElementTree as ET

    ident = str(identifier or "").strip()
    if not ident:
        raise ValueError("请输入 DOI 或 arXiv 编号")
    if ident.lower().startswith("10.") or "doi.org/" in ident.lower() or "dx.doi.org/" in ident.lower():
        doi = ident
        for pfx in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:", "DOI:"):
            if doi.lower().startswith(pfx.lower()):
                doi = doi[len(pfx):]
        doi = doi.strip()
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = data.get("message") or {}
        raw_title = msg.get("title")
        title = " ".join(raw_title).strip() if isinstance(raw_title, list) else str(raw_title or "").strip()
        authors = "; ".join(
            f"{a.get('given','')} {a.get('family','')}".strip()
            for a in msg.get("author") or [] if isinstance(a, dict)
        )
        year = ""
        for key in ("published-print", "published-online", "issued", "created"):
            parts = (msg.get(key) or {}).get("date-parts") or []
            if parts and parts[0] and parts[0][0]:
                year = str(parts[0][0])
                break
        venue = ""
        ct = msg.get("container-title")
        if isinstance(ct, list) and ct:
            venue = str(ct[0])
        elif isinstance(ct, str) and ct:
            venue = ct
        return {
            "title": title, "authors": authors, "year": year, "venue": venue,
            "doi": doi, "url": str(msg.get("URL") or f"https://doi.org/{doi}"),
            "cite_key": _cite_key_from(title, year, authors),
        }
    m = re.match(r"^(?:arxiv[:/]\s*|arxiv\.org/abs/)?(\d{4}\.\d{4,5})(?:v\d+)?$", ident, re.I)
    if m:
        aid = m.group(1)
        with urllib.request.urlopen("https://export.arxiv.org/api/query?id_list=" + aid, timeout=10) as resp:
            xml_text = resp.read().decode("utf-8")
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_text)
        entries = root.findall("a:entry", ns)
        if not entries:
            raise ValueError(f"arXiv 未找到编号 {aid}")
        entry = entries[0]
        title = re.sub(r"\s+", " ", entry.findtext("a:title", "", ns) or "").strip()
        authors = "; ".join(
            (a.findtext("a:name", "", ns) or "").strip() for a in entry.findall("a:author", ns)
        )
        pub = entry.findtext("a:published", "", ns) or ""
        year = pub[:4] if pub[:4].isdigit() else ""
        return {
            "title": title, "authors": authors, "year": year, "venue": "arXiv",
            "doi": "", "url": (entry.findtext("a:id", "", ns) or "").strip(),
            "cite_key": _cite_key_from(title, year, authors),
        }
    raise ValueError("无法识别：请输入 DOI（10.… 开头）或 arXiv 编号（如 2401.02345）")

def pdf_path(paper_id: str) -> Path:
    item = get_item(paper_id)
    root = _pdf_dir().resolve()
    p = (root / str(item.get("stored_filename") or "")).resolve()
    if root not in p.parents: raise ValueError("Invalid PDF path")
    return p

def annotation_path(paper_id: str) -> Path:
    return _root() / "Annotations" / f"{paper_id}.json"

def note_path(paper_id: str) -> Path:
    return _root() / "Notes" / f"{paper_id}.md"

def preview_dir(paper_id: str) -> Path:
    p = _root() / "Previews" / str(paper_id)
    p.mkdir(parents=True, exist_ok=True)
    return p

def _save_preview_data_url(paper_id: str, ann_id: str, data_url: str) -> str:
    data_url = str(data_url or "")
    m = re.match(r"^data:image/(webp|png|jpeg);base64,(.+)$", data_url, re.I | re.S)
    if not m:
        raise ValueError("Invalid annotation preview")
    ext = {"jpeg": "jpg"}.get(m.group(1).lower(), m.group(1).lower())
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception as exc:
        raise ValueError("Invalid annotation preview encoding") from exc
    if not raw or len(raw) > 3 * 1024 * 1024:
        raise ValueError("Annotation preview is too large")
    target = preview_dir(paper_id) / f"{ann_id}.{ext}"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(target)
    return str(target.relative_to(ensure_workspace())).replace("\\", "/")

def get_annotations(paper_id: str, page: int | None = None) -> list[dict[str, Any]]:
    get_item(paper_id)
    p = annotation_path(paper_id)
    if not p.exists(): return []
    try: rows = json.loads(p.read_text(encoding="utf-8"))
    except Exception: rows = []
    # v260929f · 存量批注回填编号：缺 no 的按 created_at 顺序续接当前最大号，一次性写回
    # （旧批注一打开阅读区即获得编号，无需逐条编辑；save_annotation 经此读取后 existing 即带号）
    missing = [x for x in rows if not isinstance(x.get("no"), int) or int(x["no"]) <= 0]
    if missing:
        nxt = max((int(x.get("no") or 0) for x in rows), default=0) + 1
        for x in sorted(missing, key=lambda x: str(x.get("created_at") or "")):
            x["no"] = nxt; nxt += 1
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    if page is not None: rows = [x for x in rows if int(x.get("page") or 0) == int(page)]
    return rows

def save_annotation(paper_id: str, annotation: dict[str, Any]) -> dict[str, Any]:
    get_item(paper_id)
    typ = str(annotation.get("type") or "highlight")
    if typ not in ANNOTATION_TYPES:
        raise ValueError("Unsupported annotation type")
    p = annotation_path(paper_id)
    rows = get_annotations(paper_id)
    ann_id = str(annotation.get("id") or uuid.uuid4().hex)
    existing = next((x for x in rows if x.get("id") == ann_id), {}) or {}
    selection_kind = str(annotation.get("selection_kind") or existing.get("selection_kind") or "text")
    if selection_kind not in {"text", "area"}:
        selection_kind = "text"
    preview_path = str(annotation.get("preview_path") or existing.get("preview_path") or "")
    preview_data_url = str(annotation.get("preview_data_url") or "")
    if preview_data_url:
        preview_path = _save_preview_data_url(paper_id, ann_id, preview_data_url)
    # v260929f · 批注编号：编辑保留原号；新建取当前最大号 +1（删除不回收，删空后从 1 重新开始）
    no = existing.get("no")
    if not isinstance(no, int) or no <= 0:
        no = max((int(x.get("no") or 0) for x in rows), default=0) + 1
    row = {
        "id": ann_id,
        "no": no,
        "page": max(1, int(annotation.get("page") or existing.get("page") or 1)),
        "type": typ,
        "rects": annotation.get("rects") if "rects" in annotation else existing.get("rects", []),
        "points": annotation.get("points") if "points" in annotation else existing.get("points", []),
        "text": str(annotation.get("text") if "text" in annotation else existing.get("text", ""))[:20000],
        "comment": str(annotation.get("comment") if "comment" in annotation else existing.get("comment", ""))[:20000],
        "color": str(annotation.get("color") or existing.get("color") or "yellow"),
        "selection_kind": selection_kind,
        "preview_path": preview_path,
        "created_at": existing.get("created_at") or annotation.get("created_at") or datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    rows = [x for x in rows if x.get("id") != ann_id] + [row]
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return row

def delete_annotation(paper_id: str, annotation_id: str) -> dict[str, Any]:
    rows = get_annotations(paper_id)
    victim = next((x for x in rows if x.get("id") == annotation_id), None)
    rows = [x for x in rows if x.get("id") != annotation_id]
    p = annotation_path(paper_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    if victim and victim.get("preview_path"):
        target = (ensure_workspace() / str(victim["preview_path"])).resolve()
        root = ensure_workspace().resolve()
        if root in target.parents and target.is_file():
            try:
                target.unlink()
            except OSError:
                pass
    return {"ok": True}

def _note_doc_id(paper_id: str) -> str:
    """v260929 · 阅读区「笔记」的真值 = 该文献关联的知识条目 md（frontmatter 之后的正文），
    与文献编辑器里的「文献笔记」正文同源，避免同一篇文献存在两份笔记。"""
    doc_id = str(get_item(paper_id).get("doc_id") or "")
    if not doc_id:
        raise ValueError(f"文献条目不完整，缺少 doc_id 关联：{paper_id}")
    return doc_id

def get_note(paper_id: str) -> str:
    from . import store
    return str(store.get_doc(_note_doc_id(paper_id)).get("body") or "")

def save_note(paper_id: str, content: str) -> dict[str, Any]:
    from . import indexer
    doc_id = _note_doc_id(paper_id)
    indexer.update_doc(doc_id, {"body": str(content or "")})  # 经 indexer 写回 md 并刷新索引，文献编辑器读取同一份正文
    return {"ok": True, "doc_id": doc_id}
