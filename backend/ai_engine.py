"""Multi-AI ensemble for trading analysis.

Calls GPT-5-mini (OpenAI), Claude Sonnet 4.6 (Anthropic), and Gemini 3.5 Flash
(Google) in parallel via emergentintegrations, then aggregates into a
consensus signal with news/macro context.

Multi-vendor combo chosen for:
- Cost efficiency (~80% cheaper than the previous 3x Claude combo)
- Ensemble diversity (three different vendor training corpora / bias
  profiles → more robust consensus than three Claude variants)
- Provider redundancy (if one provider is rate-limited, the other two
  still return a signal)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from typing import Any

from emergentintegrations.llm.chat import LlmChat, UserMessage

MODELS = [
    # Cost-optimised multi-provider ensemble (v7.0.2). Whenever a newer
    # model is available in the Emergent LLM catalog, only this list has to
    # change — the frontend picks up the new labels via GET /api/ai/models.
    {"provider": "openai", "model": "gpt-5-mini", "label": "GPT-5 mini"},
    {"provider": "anthropic", "model": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"provider": "gemini", "model": "gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
]


# Language-specific system prompts. Frontend passes `?lang=en|id|ru|cn`
# through to the analyze endpoint; anything unknown falls back to English.
_LANG_SYSTEM = {
    "id": (
        "Anda adalah analis trading senior multi-aset (crypto, saham global, "
        "forex, komoditas, emas/perak). Berikan analisa singkat, tajam, "
        "berbasis data teknikal yang diberikan, DAN konteks makro/berita/"
        "politik/ekonomi terkini yang Anda ketahui. Selalu balas dalam format "
        "JSON yang valid SAJA, tanpa markdown, tanpa teks lain. "
        "Bahasa jawaban: Bahasa Indonesia."
    ),
    "en": (
        "You are a senior multi-asset trading analyst (crypto, global equities, "
        "forex, commodities, gold/silver). Provide a short, sharp analysis "
        "grounded in the technical data supplied AND the latest macro / news / "
        "political / economic context you are aware of. Always respond with "
        "VALID JSON ONLY — no markdown, no extra prose. "
        "Response language: English."
    ),
    "ru": (
        "Вы старший мульти-активный трейдинг-аналитик (криптовалюты, мировые "
        "акции, форекс, товары, золото/серебро). Дайте краткий, чёткий анализ, "
        "основанный на предоставленных технических данных и на актуальном "
        "макро/новостном/политическом/экономическом контексте, который вы "
        "знаете. Всегда отвечайте ТОЛЬКО валидным JSON — без markdown, без "
        "дополнительного текста. Язык ответа: русский."
    ),
    "cn": (
        "你是一位资深多资产交易分析师（加密货币、全球股票、外汇、商品、"
        "黄金/白银）。请基于所提供的技术数据以及你所了解的最新宏观/新闻/"
        "政治/经济背景，给出简明、犀利的分析。仅以有效的 JSON 格式回复，"
        "不要 markdown，不要额外文字。回复语言：中文。"
    ),
}


def _system_prompt_for(lang: str) -> str:
    return _LANG_SYSTEM.get((lang or "en").lower(), _LANG_SYSTEM["en"])

JSON_SCHEMA = """{
  "action": "BUY" | "SELL" | "HOLD",
  "label": "LONG" | "SHORT" | "BUY" | "SELL" | "HOLD",
  "confidence": <int 0-100>,
  "summary": "<2-3 kalimat ringkas alasan utama>",
  "entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "timeframe_view": "<pandangan singkat untuk timeframe ini>",
  "news_factors": ["<faktor berita/makro 1>", "<faktor 2>", "<faktor 3>"],
  "risk_factors": ["<risiko 1>", "<risiko 2>"]
}"""


_MARKET_NAMES = {
    "id": {
        "crypto": "Cryptocurrency (Binance)",
        "stock_id": "Saham Indonesia (IDX)",
        "stock_us": "Saham AS (US Stocks)",
        "etf": "ETF",
        "gold_silver": "Emas/Perak",
        "commodity": "Komoditas",
        "forex": "Forex",
    },
    "en": {
        "crypto": "Cryptocurrency (Binance)",
        "stock_id": "Indonesian Stocks (IDX)",
        "stock_us": "US Stocks",
        "etf": "ETF",
        "gold_silver": "Gold / Silver",
        "commodity": "Commodities",
        "forex": "Forex",
    },
}


_PROMPT_TEMPLATES = {
    "id": {
        "news_header": "\n\nBerita & headline terkini (live RSS feed):\n",
        "body": (
            "Analisa aset berikut:\n"
            "- Simbol: {symbol}\n"
            "- Market: {market}\n"
            "- Timeframe analisa: {timeframe}\n"
            "- Harga saat ini: {price}\n"
            "- Indikator teknikal terhitung:\n"
            "  - RSI(14): {rsi}\n  - EMA20: {ema20}\n  - EMA50: {ema50}\n"
            "  - MACD histogram: {macd}\n  - ATR(14): {atr}\n"
            "- Sinyal rule-based: {action} ({label}) confidence {conf}%\n"
            "- Alasan teknis: {reasons}{news_block}\n\n"
            "Pertimbangkan berita di atas (jika ada) bersama konteks makro & "
            "berita global/Indonesia terkini yang Anda ketahui.\n\n"
            "Berikan rekomendasi trading. Balas HANYA dengan JSON sesuai skema:\n"
            "{schema}"
        ),
    },
    "en": {
        "news_header": "\n\nLatest news & headlines (live RSS feed):\n",
        "body": (
            "Analyse the following asset:\n"
            "- Symbol: {symbol}\n"
            "- Market: {market}\n"
            "- Timeframe: {timeframe}\n"
            "- Current price: {price}\n"
            "- Technical indicators:\n"
            "  - RSI(14): {rsi}\n  - EMA20: {ema20}\n  - EMA50: {ema50}\n"
            "  - MACD histogram: {macd}\n  - ATR(14): {atr}\n"
            "- Rule-based signal: {action} ({label}) confidence {conf}%\n"
            "- Technical reasons: {reasons}{news_block}\n\n"
            "Consider the news above (if any) together with the current global "
            "macro / political / economic context you know.\n\n"
            "Return a trading recommendation. Respond ONLY with JSON matching this schema:\n"
            "{schema}"
        ),
    },
}


def _build_prompt(symbol: str, market: str, timeframe: str, ta: dict[str, Any], price: float, news: list[dict[str, Any]] | None = None, lang: str = "en") -> str:
    lang_key = (lang or "en").lower()
    if lang_key not in _PROMPT_TEMPLATES:
        lang_key = "en"
    tpl = _PROMPT_TEMPLATES[lang_key]
    market_map = _MARKET_NAMES.get(lang_key, _MARKET_NAMES["en"])
    market_name = market_map.get(market, market)
    news_block = ""
    if news:
        lines = []
        for n in news[:8]:
            src = n.get("source", "")
            title = (n.get("title") or "").strip()
            pub = (n.get("published") or "")[:10]
            lines.append(f"- [{pub}] ({src}) {title}")
        news_block = tpl["news_header"] + "\n".join(lines)
    return tpl["body"].format(
        symbol=symbol,
        market=market_name,
        timeframe=timeframe,
        price=price,
        rsi=ta.get("rsi"),
        ema20=ta.get("ema20"),
        ema50=ta.get("ema50"),
        macd=ta.get("macd_hist"),
        atr=ta.get("atr"),
        action=ta.get("action"),
        label=ta.get("label"),
        conf=ta.get("confidence"),
        reasons="; ".join(ta.get("reasons", [])),
        news_block=news_block,
        schema=JSON_SCHEMA,
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    # Strip code fences
    text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    # Find first {...} block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def _call_one(model_cfg: dict[str, str], prompt: str, session_id: str, lang: str = "en") -> dict[str, Any]:
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    system_prompt = _system_prompt_for(lang)

    async def _try(provider: str, model: str, label: str) -> tuple[bool, dict[str, Any]]:
        try:
            chat = LlmChat(
                api_key=api_key,
                session_id=session_id,
                system_message=system_prompt,
            ).with_model(provider, model)
            response = await chat.send_message(UserMessage(text=prompt))
            text = response if isinstance(response, str) else str(response)
            parsed = _extract_json(text)
            if parsed:
                return True, {"model": label, "ok": True, "data": parsed}
            return False, {"model": label, "ok": False, "error": "parse_failed", "raw": text[:300]}
        except Exception as e:
            return False, {"model": label, "ok": False, "error": str(e)[:200]}

    ok, result = await _try(model_cfg["provider"], model_cfg["model"], model_cfg["label"])
    if ok:
        return result

    # Optional fallback (e.g., Fable 5 → Opus 4.8 kalau Emergent belum whitelist Fable 5)
    fb_model = model_cfg.get("fallback_model")
    if fb_model:
        fb_label = model_cfg.get("fallback_label", f"{fb_model} (fallback)")
        ok2, result2 = await _try(model_cfg["provider"], fb_model, fb_label)
        if ok2:
            return result2
        # Kalau fallback juga gagal, return error dari primary tapi tandai fallback juga fail
        result["fallback_error"] = result2.get("error", "unknown")
    return result


_FALLBACK_STRINGS = {
    "id": {
        "no_valid": "Tidak ada respons valid dari model AI. Menampilkan sinyal teknikal saja.",
        "based_on_ta": "Berdasarkan indikator teknikal lokal.",
        "no_ai": "Data AI tidak tersedia",
        "consensus": "Konsensus model AI.",
    },
    "en": {
        "no_valid": "No valid AI response — showing technical signal only.",
        "based_on_ta": "Based on local technical indicators.",
        "no_ai": "AI data unavailable",
        "consensus": "AI model consensus.",
    },
    "ru": {
        "no_valid": "Нет корректного ответа от ИИ — показан только технический сигнал.",
        "based_on_ta": "На основании локальных технических индикаторов.",
        "no_ai": "Данные ИИ недоступны",
        "consensus": "Консенсус ИИ-моделей.",
    },
    "cn": {
        "no_valid": "AI 无有效响应 — 仅显示技术信号。",
        "based_on_ta": "基于本地技术指标。",
        "no_ai": "AI 数据不可用",
        "consensus": "AI 模型共识。",
    },
}


def _aggregate(results: list[dict[str, Any]], fallback_ta: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    lang_key = (lang or "en").lower()
    if lang_key not in _FALLBACK_STRINGS:
        lang_key = "en"
    strings = _FALLBACK_STRINGS[lang_key]
    valid = [r["data"] for r in results if r.get("ok") and isinstance(r.get("data"), dict)]
    if not valid:
        return {
            "action": fallback_ta.get("action", "HOLD"),
            "label": fallback_ta.get("label", "HOLD"),
            "confidence": fallback_ta.get("confidence", 50),
            "summary": strings["no_valid"],
            "entry": fallback_ta.get("entry"),
            "stop_loss": fallback_ta.get("stop_loss"),
            "take_profit": fallback_ta.get("take_profit"),
            "timeframe_view": strings["based_on_ta"],
            "news_factors": [],
            "risk_factors": [strings["no_ai"]],
        }

    # Vote for action
    action_votes: dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
    confidences: list[int] = []
    entries: list[float] = []
    sls: list[float] = []
    tps: list[float] = []
    news_all: list[str] = []
    risks_all: list[str] = []
    summaries: list[str] = []
    timeframe_views: list[str] = []

    for d in valid:
        a = str(d.get("action", "HOLD")).upper()
        if a not in action_votes:
            a = "HOLD"
        action_votes[a] += 1
        try:
            confidences.append(int(d.get("confidence") or 0))
        except Exception:
            pass
        for key, bucket in (("entry", entries), ("stop_loss", sls), ("take_profit", tps)):
            v = d.get(key)
            if isinstance(v, (int, float)):
                bucket.append(float(v))
        nf = d.get("news_factors") or []
        if isinstance(nf, list):
            news_all.extend([str(x) for x in nf][:5])
        rf = d.get("risk_factors") or []
        if isinstance(rf, list):
            risks_all.extend([str(x) for x in rf][:5])
        if d.get("summary"):
            summaries.append(str(d["summary"]))
        if d.get("timeframe_view"):
            timeframe_views.append(str(d["timeframe_view"]))

    action = max(action_votes, key=lambda k: action_votes[k])
    # Confidence boosted by consensus
    base_conf = round(sum(confidences) / len(confidences)) if confidences else 60
    consensus_ratio = action_votes[action] / max(1, len(valid))
    final_conf = min(98, round(base_conf * 0.7 + consensus_ratio * 100 * 0.3))

    # Determine label
    is_crypto = fallback_ta.get("_is_crypto", False)
    if action == "BUY":
        label = "LONG" if is_crypto else "BUY"
    elif action == "SELL":
        label = "SHORT" if is_crypto else "SELL"
    else:
        label = "HOLD"

    def _avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 8) if xs else None

    # Dedupe news/risks
    seen: set[str] = set()
    news_dedup: list[str] = []
    for n in news_all:
        k = n.strip().lower()
        if k and k not in seen:
            seen.add(k)
            news_dedup.append(n.strip())
    seen2: set[str] = set()
    risks_dedup: list[str] = []
    for n in risks_all:
        k = n.strip().lower()
        if k and k not in seen2:
            seen2.add(k)
            risks_dedup.append(n.strip())

    return {
        "action": action,
        "label": label,
        "confidence": int(final_conf),
        "summary": summaries[0] if summaries else strings["consensus"],
        "entry": _avg(entries) or fallback_ta.get("entry"),
        "stop_loss": _avg(sls) or fallback_ta.get("stop_loss"),
        "take_profit": _avg(tps) or fallback_ta.get("take_profit"),
        "timeframe_view": timeframe_views[0] if timeframe_views else "",
        "news_factors": news_dedup[:6],
        "risk_factors": risks_dedup[:5],
        "votes": action_votes,
    }


async def ensemble_analyze(symbol: str, market: str, timeframe: str, ta: dict[str, Any], price: float, news: list[dict[str, Any]] | None = None, lang: str = "en") -> dict[str, Any]:
    """Run all three models concurrently and aggregate.

    `news` is a list of recent headlines (from RSS feed) which is injected
    into the prompt so the AI grounds its analysis on real-time events.
    `lang` selects the response language for both the prompt and any
    fallback/aggregate strings (id / en / ru / cn). Defaults to English.
    """
    prompt = _build_prompt(symbol, market, timeframe, ta, price, news, lang=lang)
    session_base = f"{symbol}-{timeframe}-{uuid.uuid4().hex[:8]}"
    tasks = [
        _call_one(cfg, prompt, f"{session_base}-{cfg['provider']}", lang=lang)
        for cfg in MODELS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    fallback = dict(ta)
    fallback["_is_crypto"] = (market == "crypto")
    consensus = _aggregate(results, fallback, lang=lang)
    return {
        "consensus": consensus,
        "models": [
            {
                "name": r["model"],
                "ok": r["ok"],
                "data": r.get("data") if r["ok"] else None,
                "error": r.get("error"),
            }
            for r in results
        ],
    }
