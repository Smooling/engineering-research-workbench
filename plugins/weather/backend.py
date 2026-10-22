"""天气 · 插件后端 v1.0.0

从 `app/weather.py` 原样搬出（天气码表、缓存 TTL、地名解析、离线降级逻辑未改写），四处适配：

1. 配置来源：内核 `config/app.json` 的 `weather` 段 → 插件自己的 `config/plugins/weather.json`
   （`ctx.config_read/write`）。**首次运行会把内核里那份天气设置迁移过来**
   （地点/经纬度/时区/开关），老用户不用重配（PLUGIN_SPEC §11.3）。
2. 缓存位置：`Workspace/System/Cache/weather.json` → `Workspace/System/Plugins/weather/cache.json`
   （插件只碰自己命名空间，I5）。
3. 入口形态：`current(force)` / `geocode(name)` / `clear_cache()` → `register(ctx)` 注册
   `GET current` / `GET geocode` / `GET|POST config`。
4. 离线降级保持上一轮修好的行为：先退回陈旧缓存（带 `stale` 与原因），无缓存则返回显式的
   `unavailable` 载荷 —— **不抛异常、不产生 500**。

对外路由（内核挂载）：`/api/plugins/weather/current`、`/geocode`、`/config`。
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WEATHER_CODE = {
    0: "晴",
    1: "大部晴朗", 2: "局部多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "中等阵雨", 82: "强阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}
CACHE_TTL = 10 * 60

DEFAULT_CONFIG = {
    "enabled": True,
    "location": "天津市南开区",
    "latitude": 39.105,
    "longitude": 117.15,
    "timezone": "Asia/Shanghai",
}


def _json_get(url: str, timeout: float = 7.0) -> dict:
    # v261009.1 · 走 core_api.http_get：系统回环代理没启动时自动直连
    import core_api

    return json.loads(core_api.http_get(
        url, timeout=timeout, headers={"User-Agent": "EngineeringResearchWorkbench/1.0"},
    ).decode("utf-8"))


def _reason(exc: Exception) -> str:
    text = str(exc)
    if "10061" in text or "refused" in text.lower():
        return "网络不可达（连接被拒绝）"
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "网络超时"
    return f"{type(exc).__name__}: {text}"[:160]


def _adopt_legacy_cache(ctx, target) -> None:
    """一次性迁移：认领内核时代写在 `Workspace/System/Cache/weather.json` 的缓存。

    v261009 搬出内核时漏了这一步，导致断网时顶栏从「显示上次成功的实况」退化成
    「天气不可用」。认领一次之后，一律只用插件自己的缓存路径。
    """
    if target.exists():
        return
    try:
        import core_api

        legacy = core_api.data_root() / "Workspace" / "System" / "Cache" / "weather.json"
        if not legacy.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        ctx.log("已认领内核旧缓存 weather.json（断网时仍可显示上次成功的实况）")
    except OSError:
        pass


def register(ctx):
    cache_file = ctx.storage.system / "cache.json"
    _adopt_legacy_cache(ctx, cache_file)

    def _cached(cache_key: str, *, max_age: float | None) -> dict | None:
        if not cache_file.exists():
            return None
        try:
            c = json.loads(cache_file.read_text(encoding="utf-8"))
            if c.get("key") != cache_key:
                return None
            if max_age is not None and time.time() - float(c.get("timestamp", 0)) >= max_age:
                return None
            return c["data"]
        except Exception:
            return None

    def _legacy_config() -> dict:
        """一次性兼容：内核 `config/app.json` 里的 `weather` 段。"""
        import core_api

        path = core_api.data_root() / "config" / "app.json"
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            section = data.get("weather") if isinstance(data, dict) else None
            return section if isinstance(section, dict) else {}
        except Exception:
            return {}

    def config() -> dict:
        cfg = ctx.config_read(None) or {}
        if not cfg:
            migrated = _legacy_config()
            cfg = {**DEFAULT_CONFIG, **migrated} if migrated else dict(DEFAULT_CONFIG)
            if migrated:
                ctx.log(f"已从内核 app.json 迁移天气设置（{cfg.get('location')}）")
            ctx.config_write(cfg)
        return {**DEFAULT_CONFIG, **cfg}

    def geocode(name: str) -> dict:
        if not str(name or "").strip():
            return {"results": []}
        params = urlencode({"name": name, "count": 6, "language": "zh", "format": "json"})
        try:
            data = _json_get("https://geocoding-api.open-meteo.com/v1/search?" + params)
        except Exception as exc:
            return {"results": [], "unavailable": True, "reason": _reason(exc)}
        return {"results": data.get("results", [])}

    def current(force: bool = False) -> dict:
        cfg = config()
        if not cfg.get("enabled", True):
            return {"enabled": False}
        cache_key = json.dumps({k: cfg.get(k) for k in ("location", "latitude", "longitude", "timezone")},
                               ensure_ascii=False, sort_keys=True)
        fresh = _cached(cache_key, max_age=CACHE_TTL)
        if fresh is not None and not force:
            return fresh
        try:
            lat = cfg.get("latitude"); lon = cfg.get("longitude"); tz = cfg.get("timezone") or "auto"
            if lat is None or lon is None:
                results = geocode(str(cfg.get("location") or "")).get("results") or []
                if not results:
                    raise ValueError("无法解析天气地点")
                lat, lon = results[0]["latitude"], results[0]["longitude"]
                tz = results[0].get("timezone") or tz
            params = {
                "latitude": lat, "longitude": lon, "timezone": tz,
                "current": "temperature_2m,apparent_temperature,weather_code,precipitation,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 3,
            }
            data = _json_get("https://api.open-meteo.com/v1/forecast?" + urlencode(params))
        except Exception as exc:
            stale = _cached(cache_key, max_age=None)
            if stale is not None:
                return {**stale, "stale": True, "reason": _reason(exc)}
            return {"enabled": True, "unavailable": True, "reason": _reason(exc),
                    "location": cfg.get("location") or "当前位置",
                    "current": {}, "daily": [], "provider": "Open-Meteo"}
        cur = data.get("current", {}); daily = data.get("daily", {}); times = daily.get("time", [])
        days = []
        for i, dt in enumerate(times):
            code = (daily.get("weather_code") or [None] * len(times))[i]
            days.append({
                "date": dt,
                "condition": WEATHER_CODE.get(code, f"天气代码 {code}"),
                "high": (daily.get("temperature_2m_max") or [None] * len(times))[i],
                "low": (daily.get("temperature_2m_min") or [None] * len(times))[i],
                "precip_probability": (daily.get("precipitation_probability_max") or [None] * len(times))[i],
            })
        result = {
            "enabled": True,
            "location": cfg.get("location") or "当前位置",
            "latitude": data.get("latitude", lat), "longitude": data.get("longitude", lon),
            "timezone": data.get("timezone", tz),
            "current": {
                "temperature": cur.get("temperature_2m"), "apparent": cur.get("apparent_temperature"),
                "condition": WEATHER_CODE.get(cur.get("weather_code"), str(cur.get("weather_code"))),
                "precipitation": cur.get("precipitation"), "wind_speed": cur.get("wind_speed_10m"),
            },
            "daily": days,
            "provider": "Open-Meteo",
        }
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"timestamp": time.time(), "key": cache_key, "data": result},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache_file)
        return result

    # ---- 路由 ----
    def route_current(request):
        force = str((request["query"].get("force") or [""])[0]) == "1"
        return current(force=force)

    def route_geocode(request):
        name = str((request["query"].get("name") or [""])[0])
        return geocode(name)

    def route_get_config(request):
        return config()

    def route_set_config(request):
        body = request.get("body") or {}
        cfg = config()
        for key in ("enabled", "location", "timezone"):
            if key in body:
                cfg[key] = body[key]
        for key in ("latitude", "longitude"):
            if key in body and str(body[key]).strip() != "":
                try:
                    cfg[key] = float(body[key])
                except (TypeError, ValueError):
                    pass
        ctx.config_write(cfg)
        if str((request["query"].get("refresh") or [""])[0]) == "1":
            return {"config": cfg, "weather": current(force=True)}
        return cfg

    ctx.routes.get("current", route_current)
    ctx.routes.get("geocode", route_geocode)
    ctx.routes.get("config", route_get_config)
    ctx.routes.post("config", route_set_config)
    ctx.log("天气插件已注册（/api/plugins/weather/current|geocode|config）")
