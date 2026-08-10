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


# v8.1.7 — Hybrid prompt: informatif seperti v2.1.8 + rich macro seperti
# v8.1.5, tapi tetap konsisten karena angka entry/SL/TP dari formula
# deterministik. AI hanya menyumbang: action vote, confidence, insight
# analisa (technical + macro + news + risk), dan entry_bias.
_LANG_SYSTEM = {
    "id": (
        "Anda adalah analis trading multi-aset senior (crypto, saham global, "
        "forex, komoditas, emas/perak). Berikan analisa yang ringkas namun "
        "kaya insight, menggabungkan: (1) data teknikal yang diberikan, "
        "(2) konteks makro/berita/kebijakan yang relevan yang Anda ketahui, "
        "(3) sentimen pasar terkini. Fokus pada faktor yang benar-benar "
        "menggerakkan harga aset ini — bukan copy-paste generic. Balas hanya "
        "dalam format JSON valid (tanpa markdown/prosa tambahan). Bahasa: "
        "Indonesia. Panjang summary 3-5 kalimat."
    ),
    "en": (
        "You are a senior multi-asset trading analyst (crypto, global equities, "
        "forex, commodities, gold/silver). Deliver a concise but insight-rich "
        "analysis combining: (1) the technical data given, (2) relevant macro/"
        "news/policy context you are aware of, (3) current market sentiment. "
        "Focus on factors that are actually moving THIS asset — no generic "
        "boilerplate. Respond with VALID JSON ONLY (no markdown / extra prose). "
        "Language: English. Summary length: 3-5 sentences."
    ),
    "ru": (
        "Вы старший мульти-активный трейдинг-аналитик (криптовалюты, мировые "
        "акции, форекс, товары, золото/серебро). Дайте краткий, но насыщенный "
        "инсайтом анализ, объединяющий: (1) предоставленные технические данные, "
        "(2) актуальный макро/новостной/политический контекст, который вы знаете, "
        "(3) текущий рыночный сентимент. Сосредоточьтесь на факторах, реально "
        "движущих ИМЕННО этот актив — без общих клише. Отвечайте ТОЛЬКО валидным "
        "JSON (без markdown/прозы). Язык: русский. Резюме: 3-5 предложений."
    ),
    "cn": (
        "你是一位资深多资产交易分析师（加密货币、全球股票、外汇、商品、"
        "黄金/白银）。请给出简明但富含洞察的分析，结合：(1) 所提供的技术"
        "数据，(2) 你所了解的相关宏观/新闻/政策背景，(3) 当前市场情绪。"
        "聚焦于真正推动该资产的因素——避免泛泛而谈。仅返回有效 JSON"
        "（不含 markdown / 说明文字）。语言：中文。摘要长度：3-5 句。"
    ),
}


def _system_prompt_for(lang: str) -> str:
    return _LANG_SYSTEM.get((lang or "en").lower(), _LANG_SYSTEM["en"])

JSON_SCHEMA = """{
  "action": "BUY" | "SELL" | "HOLD",
  "label": "LONG" | "SHORT" | "BUY" | "SELL" | "HOLD",
  "confidence": <int 0-100>,
  "summary": "<3-5 kalimat: gabungkan sinyal teknikal + konteks makro/berita + sentimen — kenapa aset ini bergerak sekarang>",
  "entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "entry_bias": "deep" | "moderate" | "aggressive",
  "timeframe_view": "<1-2 kalimat: pandangan untuk timeframe ini — trend, momentum, level penting>",
  "macro_context": "<1-2 kalimat: kondisi makro/kebijakan/sektor terkini yang mempengaruhi aset ini>",
  "news_factors": ["<berita/katalis 1 yang relevan>", "<katalis 2>", "<katalis 3>"],
  "risk_factors": ["<risiko/pemberat 1>", "<risiko 2>", "<risiko 3>"]
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
    # v8.1.6 — Vote for entry bias level (deep = safest, aggressive = closest to price).
    bias_votes: dict[str, int] = {"deep": 0, "moderate": 0, "aggressive": 0}
    confidences: list[int] = []
    news_all: list[str] = []
    risks_all: list[str] = []
    summaries: list[str] = []
    timeframe_views: list[str] = []
    macro_contexts: list[str] = []

    for d in valid:
        a = str(d.get("action", "HOLD")).upper()
        if a not in action_votes:
            a = "HOLD"
        action_votes[a] += 1
        try:
            confidences.append(int(d.get("confidence") or 0))
        except Exception:
            pass
        # Bias vote — anything unknown defaults to "deep" (safest).
        bias = str(d.get("entry_bias") or "deep").lower()
        if bias not in bias_votes:
            bias = "deep"
        bias_votes[bias] += 1
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
        if d.get("macro_context"):
            macro_contexts.append(str(d["macro_context"]))

    action = max(action_votes, key=lambda k: action_votes[k])
    consensus_bias = max(bias_votes, key=lambda k: bias_votes[k])
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

    # v8.1.6 — Deterministic entry/SL/TP from pre-computed level map.
    # If AI picked BUY, use fallback_ta._all_levels['BUY']; SELL likewise.
    # HOLD uses the technical fallback (no strong bias either way).
    all_levels = fallback_ta.get("_all_levels") or {}
    if action in ("BUY", "SELL") and all_levels.get(action):
        side = all_levels[action]
        # Map bias → key in side dict.
        entry_key = {
            "deep": "entry",
            "moderate": "entry_moderate",
            "aggressive": "entry_aggressive",
        }[consensus_bias]
        sl_key = {
            "deep": "stop_loss",
            "moderate": "stop_loss_moderate",
            "aggressive": "stop_loss_aggressive",
        }[consensus_bias]
        # v8.1.9 — Zone (low/high) around the chosen bias tier.
        zone_low_key = {
            "deep": "entry_low",
            "moderate": "entry_moderate_low",
            "aggressive": "entry_aggressive_low",
        }[consensus_bias]
        zone_high_key = {
            "deep": "entry_high",
            "moderate": "entry_moderate_high",
            "aggressive": "entry_aggressive_high",
        }[consensus_bias]
        entry_out = side.get(entry_key, side.get("entry"))
        sl_out = side.get(sl_key, side.get("stop_loss"))
        tp_out = side.get("take_profit")
        # v8.7.23 — Pass laddered TP-2 / TP-3 through to AI consensus.
        tp2_out = side.get("take_profit_2")
        tp3_out = side.get("take_profit_3")
        entry_low_out = side.get(zone_low_key)
        entry_high_out = side.get(zone_high_key)
    else:
        entry_out = fallback_ta.get("entry")
        sl_out = fallback_ta.get("stop_loss")
        tp_out = fallback_ta.get("take_profit")
        tp2_out = fallback_ta.get("take_profit_2")
        tp3_out = fallback_ta.get("take_profit_3")
        entry_low_out = fallback_ta.get("entry_low")
        entry_high_out = fallback_ta.get("entry_high")

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

    # v8.2.3 — Strip "long"/"short" jargon from all narrative fields when the
    # market is not crypto. Users flagged that stocks/ETFs/forex should never
    # surface those crypto-derivative terms in the summary paragraph.
    def _sanitize(text: str) -> str:
        if not text or is_crypto:
            return text
        out = text
        for pat, repl in (
            (r"\blong[- ]?position(s)?\b", "buy position\\1"),
            (r"\bshort[- ]?position(s)?\b", "sell position\\1"),
            (r"\bgo(ing)? long\b", "buy\\1"),
            (r"\bgo(ing)? short\b", "sell\\1"),
            (r"\bshort[- ]?selling\b", "selling"),
            (r"\bLONG\b", "BUY"),
            (r"\bSHORT\b", "SELL"),
            (r"\bLong\b", "Buy"),
            (r"\bShort\b", "Sell"),
            (r"\blong\b(?!\s+(term|-term|run))", "buy"),   # keep "long term"/"long run"
            (r"\bshort\b(?!\s+(term|-term|run))", "sell"), # keep "short term"/"short run"
        ):
            out = re.sub(pat, repl, out)
        return out

    summary_out = summaries[0] if summaries else strings["consensus"]
    tf_view_out = timeframe_views[0] if timeframe_views else ""
    macro_out = macro_contexts[0] if macro_contexts else ""
    summary_out = _sanitize(summary_out)
    tf_view_out = _sanitize(tf_view_out)
    macro_out = _sanitize(macro_out)
    news_dedup = [_sanitize(n) for n in news_dedup]
    risks_dedup = [_sanitize(r) for r in risks_dedup]

    return {
        "action": action,
        "label": label,
        "confidence": int(final_conf),
        "summary": summary_out,
        "entry": entry_out,
        "entry_low": entry_low_out,
        "entry_high": entry_high_out,
        "stop_loss": sl_out,
        "take_profit": tp_out,
        # v8.7.23 — Laddered R:R targets (regime-aware crypto only).
        "take_profit_2": tp2_out,
        "take_profit_3": tp3_out,
        "entry_bias": consensus_bias,
        "timeframe_view": tf_view_out,
        "macro_context": macro_out,
        "news_factors": news_dedup[:6],
        "risk_factors": risks_dedup[:5],
        "votes": action_votes,
        "bias_votes": bias_votes,
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
    # v8.2.1 — Normalize per-model label based on market. Saham/ETF/etc
    # tidak pakai istilah LONG/SHORT — hanya crypto. AI kadang return
    # LONG/SHORT untuk saham juga, kita fix di sini.
    is_crypto = (market == "crypto")
    for r in results:
        data = r.get("data") if r.get("ok") else None
        if not data:
            continue
        lbl = str(data.get("label") or "").upper()
        if not is_crypto:
            if lbl == "LONG":
                data["label"] = "BUY"
            elif lbl == "SHORT":
                data["label"] = "SELL"
    fallback = dict(ta)
    fallback["_is_crypto"] = is_crypto
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
