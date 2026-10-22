"""RSS 科研资讯 · 插件后端 v1.0.0

从 `app/rss.py` 原样搬出（解析/抓取/去重/陈旧回退逻辑未改写），三处适配：

1. 配置来源：内核的 `config/rss.json` → 插件自己的 `config/plugins/rss.json`
   （`ctx.config_read/write`）。**首次运行会把内核旧配置里的源导入过来**，
   老用户的资讯源不会丢（PLUGIN_SPEC §11.3 兼容与降级）。
2. 缓存位置：`Workspace/System/Cache/rss_cache.json` → 插件自己的
   `Workspace/System/Plugins/rss/cache.json`（插件只碰自己命名空间，I5）。
3. 入口形态：`fetch(force)` → `register(ctx)` 里注册 `GET feed` / `GET|POST config`。

对外路由（内核挂载）：`/api/plugins/rss/feed`、`/api/plugins/rss/config`。
"""

from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CACHE_TTL = 15 * 60
MAX_BYTES = 8 * 1024 * 1024

DEFAULT_CONFIG = {
    "sources": [
        {"name": "arXiv · Artificial Intelligence", "url": "https://rss.arxiv.org/rss/cs.AI", "enabled": True},
        {"name": "arXiv · Machine Learning", "url": "https://rss.arxiv.org/rss/cs.LG", "enabled": True},
        {"name": "arXiv · Computation and Language", "url": "https://rss.arxiv.org/rss/cs.CL", "enabled": True},
    ],
    "max_items_per_source": 12,
}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node, names: set[str]) -> str:
    for child in list(node):
        if _local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _parse_feed(xml: bytes, source_name: str, limit: int) -> list[dict]:
    root = ET.fromstring(xml)
    items: list[dict] = []
    for item in [n for n in root.iter() if _local_name(n.tag) == "item"][:limit]:
        items.append({
            "title": _child_text(item, {"title"}),
            "url": _child_text(item, {"link"}),
            "published": _child_text(item, {"pubdate", "date", "published", "updated"}),
            "summary": _strip_html(_child_text(item, {"description", "summary", "content", "encoded"}))[:800],
            "source": source_name,
        })
    if items:
        return items
    for entry in [n for n in root.iter() if _local_name(n.tag) == "entry"][:limit]:
        link = ""
        for child in list(entry):
            if _local_name(child.tag) == "link":
                href = child.attrib.get("href") or ""
                rel = child.attrib.get("rel") or "alternate"
                if href and (rel == "alternate" or not link):
                    link = href
        items.append({
            "title": _child_text(entry, {"title"}),
            "url": link,
            "published": _child_text(entry, {"published", "updated"}),
            "summary": _strip_html(_child_text(entry, {"summary", "content"}))[:800],
            "source": source_name,
        })
    return items


def _candidate_urls(source: dict, limit: int) -> list[str]:
    url = str(source.get("url") or "").strip()
    urls = [url] if url else []
    fallback = str(source.get("fallback_url") or "").strip()
    if fallback:
        urls.append(fallback)
    # arXiv 的 RSS 在部分网络下不可用，回退到官方 Atom API
    m = re.search(r"rss\.arxiv\.org/rss/([^/?#]+)", url)
    if m:
        category = m.group(1)
        api = (f"https://export.arxiv.org/api/query?search_query={quote('cat:' + category)}"
               f"&start=0&max_results={limit}&sortBy=submittedDate&sortOrder=descending")
        urls.extend([api, api.replace("https://", "http://", 1)])
    out = []
    for x in urls:
        if x and x not in out:
            out.append(x)
    return out


def _download(url: str) -> bytes:
    # v261009.1 · 走 core_api.http_get：系统回环代理没启动时自动直连，
    # 避免「代理死端口 → 所有源都连接被拒」把资讯整体打瘫。
    import core_api

    return core_api.http_get(
        url,
        timeout=12,
        headers={
            "User-Agent": "Workbench/260920.2 (+local research RSS reader)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.5",
        },
        limit=MAX_BYTES,
    )


def _fetch_source(source: dict, limit: int) -> tuple[list[dict], dict]:
    errors = []
    for url in _candidate_urls(source, limit):
        for attempt in range(2):
            try:
                items = _parse_feed(_download(url), str(source.get("name") or "RSS"), limit)
                if items:
                    return items, {"source": source.get("name"), "ok": True, "count": len(items), "url": url,
                                   "fallback": url != str(source.get("url") or "")}
                errors.append(f"{url}: feed parsed but no entries")
            except (HTTPError, URLError, TimeoutError, ET.ParseError, OSError, ValueError) as e:
                errors.append(f"{url}: {e}")
            if attempt == 0:
                time.sleep(0.25)
    return [], {"source": source.get("name"), "ok": False, "count": 0,
                "url": str(source.get("url") or ""),
                "error": errors[-1] if errors else "unknown error", "attempts": errors[-6:]}


def adopt_legacy_cache(ctx, target, legacy_name: str) -> None:
    """一次性迁移：认领内核时代写在 `Workspace/System/Cache/` 的缓存。

    v261009 搬出内核时漏了这一步，导致断网时行为退化（原来是「显示上次抓到的内容」，
    变成「0 条 + 全部获取失败」）。认领一次之后，一律只用插件自己的缓存路径。
    """
    if target.exists():
        return
    try:
        import core_api

        legacy = core_api.data_root() / "Workspace" / "System" / "Cache" / legacy_name
        if not legacy.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        ctx.log(f"已认领内核旧缓存 {legacy_name}（断网时仍可显示上次成功抓到的内容）")
    except OSError:
        pass


def register(ctx):
    cache_file = ctx.storage.system / "cache.json"
    adopt_legacy_cache(ctx, cache_file, "rss_cache.json")

    def _read_cache() -> dict | None:
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _write_cache(data: dict) -> None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(cache_file)

    def _legacy_sources() -> list[dict]:
        """一次性兼容：内核 `config/rss.json` 里的源（老用户升级不丢配置）。"""
        import core_api

        legacy = core_api._data_root() / "config" / "rss.json"
        if not legacy.is_file():
            return []
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            sources = data.get("sources") if isinstance(data, dict) else None
            return [s for s in (sources or []) if isinstance(s, dict)]
        except Exception:
            return []

    def _config() -> dict:
        cfg = ctx.config_read(None) or {}
        if not cfg:
            migrated = _legacy_sources()
            cfg = {"sources": migrated} if migrated else dict(DEFAULT_CONFIG)
            if migrated:
                ctx.log(f"已从内核 config/rss.json 导入 {len(migrated)} 个资讯源")
            ctx.config_write({**DEFAULT_CONFIG, **cfg})
        merged = {"sources": list(cfg.get("sources") or []),
                  "max_items_per_source": int(cfg.get("max_items_per_source") or 12)}
        return merged

    def fetch(force: bool = False) -> dict:
        old_cache = _read_cache()
        if old_cache and not force and time.time() - float(old_cache.get("timestamp", 0)) < CACHE_TTL:
            return old_cache
        cfg = _config()
        limit = max(1, min(50, int(cfg.get("max_items_per_source", 12))))
        sources = [s for s in cfg.get("sources", []) if s.get("enabled", True) and s.get("url")]
        if not sources:
            return {"timestamp": time.time(), "updated": datetime.now().isoformat(timespec="seconds"),
                    "items": [], "errors": [], "sources": [], "message": "未配置启用的资讯源"}
        all_items: list[dict] = []
        statuses: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(sources)))) as pool:
            jobs = {pool.submit(_fetch_source, s, limit): s for s in sources}
            for fut in as_completed(jobs):
                try:
                    items, status = fut.result()
                    all_items.extend(items)
                    statuses.append(status)
                except Exception as e:
                    src = jobs[fut]
                    statuses.append({"source": src.get("name"), "ok": False, "count": 0,
                                     "url": src.get("url"), "error": str(e)})
        dedup, seen = [], set()
        for item in all_items:
            key = (item.get("url") or item.get("title") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            dedup.append(item)
        dedup.sort(key=lambda x: x.get("published") or "", reverse=True)
        errors = [{"source": x.get("source"), "error": x.get("error"), "attempts": x.get("attempts", [])}
                  for x in statuses if not x.get("ok")]
        data = {"timestamp": time.time(), "updated": datetime.now().isoformat(timespec="seconds"),
                "items": dedup, "errors": errors,
                "sources": sorted(statuses, key=lambda x: str(x.get("source") or "")), "stale": False}
        if dedup:
            _write_cache(data)
            return data
        # 全量失败时不用空结果覆盖有用缓存（与搬出前一致）
        if old_cache and old_cache.get("items"):
            stale = dict(old_cache)
            stale.update({"stale": True, "errors": errors, "sources": data["sources"],
                          "refresh_failed_at": data["updated"]})
            return stale
        return data

    # ---- 路由 ----
    def route_feed(request):
        force = str((request["query"].get("force") or [""])[0]) == "1"
        return fetch(force=force)

    def route_get_config(request):
        return _config()

    def route_set_config(request):
        body = request.get("body") or {}
        cfg = _config()
        if "sources" in body:
            cfg["sources"] = [s for s in (body["sources"] or []) if isinstance(s, dict)]
        if "max_items_per_source" in body:
            try:
                cfg["max_items_per_source"] = max(1, min(50, int(body["max_items_per_source"])))
            except (TypeError, ValueError):
                pass
        ctx.config_write(cfg)
        return cfg

    ctx.routes.get("feed", route_feed)
    ctx.routes.get("config", route_get_config)
    ctx.routes.post("config", route_set_config)
    ctx.log("RSS 插件已注册（/api/plugins/rss/feed, /api/plugins/rss/config）")
