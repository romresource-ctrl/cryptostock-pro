"""Daily push notification scheduler for AI Crypto Stock Pro.

Runs seven cron jobs per day (Asia/Jakarta local time, i.e. WIB / UTC+7)
that push a market pulse to subscribed users grouped by their language
preference. Content is built dynamically from:

- The dashboard signal batch (top BUY/LONG signal by confidence).
- The RSS news feed (freshest headline in the relevant market).

Schedule matrix (WIB):

    05:30  EN  — US market recap
    06:30  CN  — Asia pre-open
    08:45  ID  — IDX pre-market analysis
    08:45  EN  — Asia session update
    08:45  RU  — Утро рынка
    15:30  ID  — IDX close recap
    20:30  EN  — US pre-market

The scheduler is idempotent: each fire computes a deterministic
`idempotency_key = "{slot}-{yyyy-mm-dd}"` so the Emergent relay dedupes
if the pod restarts mid-fire.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from push_notifications import chunk_recipients, send_push, subscribers_by_language

logger = logging.getLogger("push_scheduler")

# --------------------- Schedule matrix (WIB / UTC+7) ---------------------

# Each entry: (slot_id, hour, minute, language, title, body_template).
# `body_template` accepts these placeholders:
#   {sym}, {label}, {conf}, {news}
# Missing fields are gracefully replaced with a sensible default so we
# never surface literal "{sym}" text.
SCHEDULE: list[dict[str, Any]] = [
    {
        "slot": "us_recap_en",
        "hour": 5,
        "minute": 30,
        "language": "en",
        "market": "stock_us",
        "title": "🇺🇸 US Market Recap",
        "body": "{sym} {label} · Conf {conf}% · {news}",
    },
    {
        "slot": "asia_preopen_cn",
        "hour": 6,
        "minute": 30,
        "language": "cn",
        "market": "world_stocks",
        "title": "📊 亚洲盘前",
        "body": "{sym} {label} · 置信度 {conf}% · {news}",
    },
    {
        "slot": "idx_premarket_id",
        "hour": 8,
        "minute": 45,
        "language": "id",
        "market": "stock_id",
        "title": "🇮🇩 IDX Pre-Market",
        "body": "{sym} {label} · Conf {conf}% · {news}",
    },
    {
        "slot": "asia_session_en",
        "hour": 8,
        "minute": 45,
        "language": "en",
        "market": "world_stocks",
        "title": "🌏 Asia Session Update",
        "body": "{sym} {label} · Conf {conf}% · {news}",
    },
    {
        "slot": "utro_rynok_ru",
        "hour": 8,
        "minute": 45,
        "language": "ru",
        "market": "world_stocks",
        "title": "🇷🇺 Утро рынка",
        "body": "{sym} {label} · Уверенность {conf}% · {news}",
    },
    {
        "slot": "idx_close_id",
        "hour": 15,
        "minute": 30,
        "language": "id",
        "market": "stock_id",
        "title": "🇮🇩 IDX Close Recap",
        "body": "{sym} {label} · Conf {conf}% · {news}",
    },
    {
        "slot": "us_premarket_en",
        "hour": 20,
        "minute": 30,
        "language": "en",
        "market": "stock_us",
        "title": "🇺🇸 US Pre-Market",
        "body": "{sym} {label} · Conf {conf}% · {news}",
    },
]


# Helper: WIB timezone (fixed +7:00). We rely on APScheduler's `timezone`
# argument to schedule cron in local wall-clock time regardless of the
# server timezone.
try:
    from zoneinfo import ZoneInfo

    WIB = ZoneInfo("Asia/Jakarta")
except Exception:  # pragma: no cover
    import pytz

    WIB = pytz.timezone("Asia/Jakarta")


# --------------------------- Content builders ---------------------------


def _localize_action(action: str, label: str, language: str, is_crypto: bool) -> str:
    """Localise the direction word. Same rules as the frontend:

    - Crypto keeps LONG/SHORT.
    - Non-crypto uses BUY/SELL, translated to BELI/JUAL for Indonesian
      users and equivalent labels for RU/CN.
    """

    a = (action or "").upper()
    l = (label or "").upper()
    if a not in ("BUY", "SELL"):
        return l or a or "HOLD"
    lang = (language or "en").lower()
    if is_crypto:
        # Same convention as frontend: keep LONG/SHORT for crypto everywhere.
        return "LONG" if a == "BUY" else "SHORT"
    # Stocks: localise BUY/SELL.
    if lang == "id":
        return "BELI" if a == "BUY" else "JUAL"
    if lang == "ru":
        return "ПОКУПКА" if a == "BUY" else "ПРОДАЖА"
    if lang == "cn":
        return "买入" if a == "BUY" else "卖出"
    return a


async def _pick_top_signal(
    get_dashboard: Callable[[str], Awaitable[list[dict[str, Any]]]],
    market: str,
) -> dict[str, Any] | None:
    """Return the highest-confidence non-HOLD signal for the market, or None."""

    try:
        rows = await get_dashboard(market)
    except Exception as e:
        logger.warning("dashboard fetch failed for %s: %s", market, e)
        return None
    # Prefer premium rows, then by confidence.
    scored = [
        r
        for r in (rows or [])
        if (r.get("action") in ("BUY", "SELL")) and (r.get("confidence") or 0) > 0
    ]
    if not scored:
        return None
    scored.sort(
        key=lambda r: (bool(r.get("is_premium")), int(r.get("confidence") or 0)),
        reverse=True,
    )
    return scored[0]


async def _pick_top_news(
    get_news: Callable[[str], Awaitable[list[dict[str, Any]]]],
    market: str,
) -> str:
    """Return the most recent headline for the market (or empty string)."""

    try:
        items = await get_news(market)
    except Exception as e:
        logger.warning("news fetch failed for %s: %s", market, e)
        return ""
    if not items:
        return ""
    top = items[0]
    return str(top.get("title") or "").strip()


def _format_body(
    template: str,
    signal: dict[str, Any] | None,
    news_title: str,
    language: str,
) -> str:
    if signal is None:
        # Neutral fallback so users never receive an empty push.
        neutral = {
            "en": "Markets steady — no strong setup right now",
            "id": "Pasar stabil — belum ada setup kuat saat ini",
            "ru": "Рынок стабилен — сильных сигналов нет",
            "cn": "市场平稳 — 暂无强势设置",
        }
        return neutral.get(language, neutral["en"]) + (f" · {news_title}" if news_title else "")
    is_crypto = (signal.get("market") == "crypto")
    label = _localize_action(
        signal.get("action") or "",
        signal.get("label") or "",
        language,
        is_crypto,
    )
    text = template.format(
        sym=signal.get("symbol", "?"),
        label=label,
        conf=int(signal.get("confidence") or 0),
        news=news_title or {
            "en": "Markets calm",
            "id": "Pasar tenang",
            "ru": "Рынок спокоен",
            "cn": "市场平静",
        }.get(language, ""),
    )
    return text[:180]  # notification body soft cap


# ------------------------------ Main runner -----------------------------


async def _run_slot(
    db: Any,
    slot: dict[str, Any],
    get_dashboard: Callable[[str], Awaitable[list[dict[str, Any]]]],
    get_news: Callable[[str], Awaitable[list[dict[str, Any]]]],
) -> None:
    """Fetch content + push to all subscribers in the slot's language cohort."""

    recipients = await subscribers_by_language(db, slot["language"])
    if not recipients:
        logger.info("slot %s: no recipients (lang=%s), skipping", slot["slot"], slot["language"])
        return

    signal = await _pick_top_signal(get_dashboard, slot["market"])
    news_title = await _pick_top_news(get_news, slot["market"])
    body = _format_body(slot["body"], signal, news_title, slot["language"])
    title = slot["title"]

    # Deep link into asset detail if we have a signal, otherwise dashboard.
    action_url: str
    if signal and signal.get("symbol"):
        action_url = f"/asset/{signal.get('market', slot['market'])}/{signal['symbol']}"
    else:
        action_url = "/"

    idempotency_root = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    idempotency = f"{slot['slot']}-{idempotency_root}"

    logger.info(
        "slot %s → %d recipients, title=%r, body=%r",
        slot["slot"],
        len(recipients),
        title,
        body,
    )

    for chunk in chunk_recipients(recipients, 100):
        try:
            await send_push(
                recipients=chunk,
                data={
                    "title": title,
                    "message": body,
                    "action_url": action_url,
                },
                idempotency_key=idempotency,
            )
        except Exception as e:
            # Never let a push failure crash the scheduler — just log.
            logger.warning("push failed for slot %s: %s", slot["slot"], e)


# ------------------------------ Scheduler API ---------------------------


def build_scheduler(
    db: Any,
    get_dashboard: Callable[[str], Awaitable[list[dict[str, Any]]]],
    get_news: Callable[[str], Awaitable[list[dict[str, Any]]]],
) -> AsyncIOScheduler:
    """Instantiate (but don't start) the scheduler with all 7 daily jobs."""

    scheduler = AsyncIOScheduler(timezone=WIB)

    for slot in SCHEDULE:
        trigger = CronTrigger(hour=slot["hour"], minute=slot["minute"], timezone=WIB)
        scheduler.add_job(
            _run_slot,
            trigger=trigger,
            id=slot["slot"],
            kwargs={
                "db": db,
                "slot": slot,
                "get_dashboard": get_dashboard,
                "get_news": get_news,
            },
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,  # 10 min after schedule miss
            replace_existing=True,
        )

    return scheduler
