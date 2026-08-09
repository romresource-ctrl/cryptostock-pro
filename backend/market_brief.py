"""Daily AI Market Brief generator (v8.7.1).

Runs 2x per day (06:00 & 18:00 WIB) — calls Claude Sonnet 4.6 via the
Emergent LLM Key to produce a rich narrative recap of the last session:

  • Opening paragraph (2-3 sentences) summarising overall market tone
  • Per-market blurb (Crypto / Stocks / Forex / Gold)
  • Top movers strip (top 3 movers per market, from live dashboard batch)
  • Top macro/news headlines
  • Sentiment score (bullish / bearish / mixed / neutral)
  • Warning zones (⚠️ risks / drawdown alerts)

The brief is generated ONCE in English then translated to id/ru/cn on-demand
(cached in Mongo). Persisted to `market_briefs` collection with TTL 48h so
users always see the freshest one available. Public endpoint:

  GET /api/market-brief?lang=id&session=latest

Frontend renders as an expandable card at the top of the News → Market
Brief tab.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger("aitrade.market_brief")

_MODEL_PROVIDER = "anthropic"
_MODEL_NAME = "claude-sonnet-4-6"

# ---------------------------- Session helpers ----------------------------

_WIB_OFFSET = timedelta(hours=7)  # WIB = UTC+7


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _wib_now() -> datetime:
    return _now_utc() + _WIB_OFFSET


def current_session() -> str:
    """Return 'morning' or 'evening' based on WIB clock.

    Morning session: 05:00-15:00 WIB (post-Asia-open through mid-day)
    Evening session: 15:00-05:00 WIB (post-close through pre-open)
    """
    h = _wib_now().hour
    return "morning" if 5 <= h < 15 else "evening"


# ---------------------------- Input context ------------------------------


async def _gather_input_context(
    get_dashboard_batch, get_news, session: str,
) -> dict[str, Any]:
    """Assemble the input data feed for the LLM prompt.

    Uses the dashboard batch (top movers per market) + latest news RSS.
    We do NOT include full 500-symbol scans — just top 5 movers + 5 headlines
    per market to keep the prompt compact and cost-efficient.
    """
    markets = ["crypto", "stock_us", "forex", "gold_silver"]

    dashboard_data: dict[str, Any] = {}
    try:
        dash = await get_dashboard_batch(markets)
        for m, payload in (dash or {}).items():
            if not isinstance(payload, dict) or "assets" not in payload:
                continue
            assets = payload.get("assets") or []
            # sort by absolute 24h change, take top 5
            sortable = [a for a in assets if a.get("change_pct_24h") is not None]
            sortable.sort(key=lambda a: -abs(a.get("change_pct_24h") or 0))
            top = sortable[:5]
            gainers = [a for a in top if (a.get("change_pct_24h") or 0) > 0]
            losers = [a for a in top if (a.get("change_pct_24h") or 0) < 0]
            dashboard_data[m] = {
                "premium_count": payload.get("premium_count", 0),
                "gainers": [
                    {
                        "symbol": a.get("symbol"),
                        "change_pct_24h": round(a.get("change_pct_24h") or 0, 2),
                        "price": a.get("price"),
                        "action": a.get("action"),
                        "confidence": a.get("confidence"),
                    }
                    for a in gainers
                ],
                "losers": [
                    {
                        "symbol": a.get("symbol"),
                        "change_pct_24h": round(a.get("change_pct_24h") or 0, 2),
                        "price": a.get("price"),
                        "action": a.get("action"),
                        "confidence": a.get("confidence"),
                    }
                    for a in losers
                ],
                "top_premium": [
                    {
                        "symbol": a.get("symbol"),
                        "action": a.get("action"),
                        "confidence": a.get("confidence"),
                        "change_pct_24h": round(a.get("change_pct_24h") or 0, 2),
                    }
                    for a in assets if a.get("is_premium")
                ][:3],
            }
    except Exception as e:
        logger.warning("dashboard context fetch failed: %s", e)

    # Latest news across all markets (10 headlines).
    news_items: list[dict[str, Any]] = []
    try:
        raw = await get_news("all")
        for n in (raw or [])[:10]:
            news_items.append(
                {
                    "title": (n.get("title") or "").strip()[:180],
                    "source": n.get("source"),
                    "published": (n.get("published") or "")[:19],
                }
            )
    except Exception as e:
        logger.warning("news context fetch failed: %s", e)

    return {
        "session": session,
        "generated_at_wib": _wib_now().strftime("%Y-%m-%d %H:%M WIB"),
        "dashboard": dashboard_data,
        "news": news_items,
    }


# ---------------------------- LLM call -----------------------------------

_BRIEF_SYSTEM = (
    "You are the senior market strategist for AITrade Pro, a professional "
    "trading dashboard. You write concise, information-dense market briefs "
    "twice a day for retail-yet-serious traders (crypto + global equities + "
    "forex + precious metals). Your voice is calm, direct, evidence-based — "
    "never hype, never generic. You reference specific tickers, macro drivers, "
    "and technical structure. Every claim must be grounded in the data feed "
    "provided. Output STRICT JSON only, no markdown."
)

_BRIEF_SCHEMA = """{
  "session": "morning" | "evening",
  "sentiment": "bullish" | "bearish" | "mixed" | "neutral",
  "sentiment_score": <int -100 to +100, where +100 = extreme bullish>,
  "summary": "<2-3 sentence lead paragraph — the ONE thing traders must know today>",
  "sections": {
    "crypto":     "<2-3 sentences: what moved, why, key level to watch>",
    "stocks":     "<2-3 sentences: US + world equities pulse>",
    "forex":      "<2-3 sentences: USD strength, major pairs, macro catalysts>",
    "gold":       "<2-3 sentences: gold/silver + commodities note>"
  },
  "top_movers": [
    {"symbol": "BTC", "market": "crypto", "change_pct_24h": 3.2, "note": "<one-liner>"},
    ...  (max 5 items, order by absolute change desc)
  ],
  "top_headlines": [
    {"title": "<verbatim from feed>", "source": "<from feed>", "why_matters": "<1 sentence>"},
    ...  (max 3 items)
  ],
  "warning_zones": [
    "<risk / drawdown / macro caveat 1>",
    "<risk 2>",
    "<risk 3>"
  ]
}"""


def _build_prompt(ctx: dict[str, Any]) -> str:
    return (
        f"Generate a Market Brief for session '{ctx['session']}' "
        f"(WIB time now: {ctx['generated_at_wib']}).\n\n"
        f"MARKET DATA FEED (top movers + premium picks per market):\n"
        f"{json.dumps(ctx['dashboard'], indent=2, default=str)}\n\n"
        f"LATEST HEADLINES (RSS live):\n"
        f"{json.dumps(ctx['news'], indent=2, default=str)}\n\n"
        f"Return VALID JSON ONLY (no markdown, no prose) matching this schema:\n"
        f"{_BRIEF_SCHEMA}\n\n"
        f"Requirements:\n"
        f"- Ground every claim in the data. Use actual ticker symbols and "
        f"percentages from the feed.\n"
        f"- Sentiment must reflect the balance of gainers/losers and macro tone.\n"
        f"- 'top_movers' MUST match items from the data feed (do not invent).\n"
        f"- 'top_headlines' MUST use verbatim titles from the feed.\n"
        f"- Language: English (translations happen separately)."
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def _call_llm(prompt: str, session_id: str) -> dict[str, Any] | None:
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        logger.error("EMERGENT_LLM_KEY missing; cannot generate market brief")
        return None
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=session_id,
            system_message=_BRIEF_SYSTEM,
        ).with_model(_MODEL_PROVIDER, _MODEL_NAME)
        response = await chat.send_message(UserMessage(text=prompt))
        text = response if isinstance(response, str) else str(response)
        parsed = _extract_json(text)
        if not parsed:
            logger.warning("market brief LLM returned non-JSON: %s", text[:300])
        return parsed
    except Exception as e:
        logger.error("market brief LLM call failed: %s", e)
        return None


# ---------------------------- Translation --------------------------------

_LANG_LABEL = {
    "id": "Indonesian (Bahasa Indonesia)",
    "ru": "Russian",
    "cn": "Simplified Chinese",
}


async def _translate_brief(brief_en: dict[str, Any], target_lang: str) -> dict[str, Any]:
    """Translate the narrative fields of a brief into target_lang.

    We only translate the human-facing strings; ticker symbols and numeric
    fields pass through untouched. If translation fails we return the EN
    version so the UI never breaks.
    """
    if target_lang == "en" or target_lang not in _LANG_LABEL:
        return brief_en
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        return brief_en

    payload = {
        "summary": brief_en.get("summary", ""),
        "sections": brief_en.get("sections", {}) or {},
        "top_movers_notes": [m.get("note", "") for m in (brief_en.get("top_movers") or [])],
        "headlines_why": [h.get("why_matters", "") for h in (brief_en.get("top_headlines") or [])],
        "warning_zones": brief_en.get("warning_zones", []) or [],
    }
    prompt = (
        f"Translate all human-readable strings in this JSON to {_LANG_LABEL[target_lang]}. "
        f"KEEP ticker symbols, prices, percentages, numbers and the JSON KEY names intact — "
        f"only the string VALUES change. Return VALID JSON with the SAME shape.\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"brief-tr-{target_lang}-{uuid.uuid4().hex[:6]}",
            system_message="You are a precise financial translator. Preserve all numbers, tickers, and JSON structure.",
        ).with_model(_MODEL_PROVIDER, _MODEL_NAME)
        resp = await chat.send_message(UserMessage(text=prompt))
        text = resp if isinstance(resp, str) else str(resp)
        parsed = _extract_json(text)
        if not parsed:
            return brief_en
    except Exception as e:
        logger.warning("brief translate failed for %s: %s", target_lang, e)
        return brief_en

    translated = dict(brief_en)
    translated["summary"] = parsed.get("summary") or brief_en.get("summary")
    translated["sections"] = parsed.get("sections") or brief_en.get("sections")
    # zip translated movers/headlines back into their structures
    mover_notes = parsed.get("top_movers_notes") or []
    tm = list(brief_en.get("top_movers") or [])
    for i, mv in enumerate(tm):
        if i < len(mover_notes):
            mv["note"] = mover_notes[i]
    translated["top_movers"] = tm
    head_why = parsed.get("headlines_why") or []
    th = list(brief_en.get("top_headlines") or [])
    for i, h in enumerate(th):
        if i < len(head_why):
            h["why_matters"] = head_why[i]
    translated["top_headlines"] = th
    translated["warning_zones"] = parsed.get("warning_zones") or brief_en.get("warning_zones")
    return translated


# ---------------------------- Public API ---------------------------------

async def generate_and_store_brief(
    db, get_dashboard_batch, get_news, *, session: str | None = None,
) -> dict[str, Any] | None:
    """Generate a brief in EN, persist to Mongo, return the stored doc.

    Called by the scheduler at 06:00 and 18:00 WIB. Idempotent per session:
    if a brief already exists for today's session slot, it gets replaced
    (upsert on `session + date`).
    """
    session = session or current_session()
    ctx = await _gather_input_context(get_dashboard_batch, get_news, session)
    brief_en = await _call_llm(
        _build_prompt(ctx),
        session_id=f"brief-{session}-{uuid.uuid4().hex[:8]}",
    )
    if not brief_en:
        return None

    now = _now_utc()
    date_key = _wib_now().strftime("%Y-%m-%d")
    doc = {
        "_id": f"{date_key}-{session}",
        "session": session,
        "date_key": date_key,
        "generated_at": now,
        "lang": "en",
        "is_original": True,
        "content": brief_en,
        "translations": {},  # populated lazily by get_brief when a non-EN lang is requested
    }

    try:
        await db.market_briefs.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        logger.info("market brief stored: %s (session=%s)", doc["_id"], session)
    except Exception as e:
        logger.error("market brief mongo store failed: %s", e)
    return doc


async def get_latest_brief(db, lang: str = "en") -> dict[str, Any] | None:
    """Return the latest brief translated to `lang` (cached in doc.translations).

    If the latest brief hasn't been translated to `lang` yet, translate on
    demand and persist. If nothing exists at all → None.
    """
    lang = (lang or "en").lower()
    doc = await db.market_briefs.find_one(sort=[("generated_at", -1)])
    if not doc:
        return None

    content_en = doc.get("content") or {}
    if lang == "en":
        return _shape(doc, content_en, lang)

    translations = doc.get("translations") or {}
    if lang in translations:
        return _shape(doc, translations[lang], lang)

    # Translate on demand + cache
    translated = await _translate_brief(content_en, lang)
    if translated is not content_en:
        try:
            await db.market_briefs.update_one(
                {"_id": doc["_id"]},
                {"$set": {f"translations.{lang}": translated}},
            )
        except Exception as e:
            logger.warning("brief translation cache write failed: %s", e)
    return _shape(doc, translated, lang)


def _shape(doc: dict[str, Any], content: dict[str, Any], lang: str) -> dict[str, Any]:
    gen = doc.get("generated_at")
    if hasattr(gen, "isoformat"):
        gen_iso = gen.isoformat()
    else:
        gen_iso = str(gen)
    return {
        "id": doc.get("_id"),
        "session": doc.get("session"),
        "date_key": doc.get("date_key"),
        "generated_at": gen_iso,
        "lang": lang,
        "sentiment": content.get("sentiment"),
        "sentiment_score": content.get("sentiment_score"),
        "summary": content.get("summary"),
        "sections": content.get("sections", {}),
        "top_movers": content.get("top_movers", []),
        "top_headlines": content.get("top_headlines", []),
        "warning_zones": content.get("warning_zones", []),
    }


async def ensure_ttl_index(db) -> None:
    """Auto-delete briefs older than 48 hours."""
    try:
        await db.market_briefs.create_index("generated_at", expireAfterSeconds=48 * 3600)
    except Exception as e:
        logger.warning("market_briefs TTL index create failed: %s", e)
