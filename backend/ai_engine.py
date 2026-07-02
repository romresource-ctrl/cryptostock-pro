"""Multi-AI ensemble for trading analysis.

Calls Claude Sonnet 4.6, GPT-5.2, and Gemini 3.1 Pro Preview in parallel
via emergentintegrations, then aggregates into a consensus signal with
news/macro context.
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
    # Semua versi terbaru per 2026 (5 AI agents ensemble)
    {"provider": "anthropic", "model": "claude-fable-5", "label": "Claude Fable 5"},
    {"provider": "anthropic", "model": "claude-opus-4-8", "label": "Claude Opus 4.8"},
    {"provider": "anthropic", "model": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"provider": "openai", "model": "gpt-5.5", "label": "GPT-5.5"},
    {"provider": "gemini", "model": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro"},
]

SYSTEM_PROMPT = (
    "Anda adalah analis trading senior multi-aset (crypto & saham Indonesia IDX). "
    "Berikan analisa singkat, tajam, berbasis data teknikal yang diberikan, "
    "DAN konteks makro/berita/politik/ekonomi terkini yang Anda ketahui. "
    "Selalu balas dalam format JSON yang valid SAJA, tanpa markdown, tanpa teks lain. "
    "Bahasa: Bahasa Indonesia."
)

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


def _build_prompt(symbol: str, market: str, timeframe: str, ta: dict[str, Any], price: float, news: list[dict[str, Any]] | None = None) -> str:
    market_name = "Cryptocurrency (Binance)" if market == "crypto" else "Saham Indonesia (IDX)"
    news_block = ""
    if news:
        lines = []
        for n in news[:8]:
            src = n.get("source", "")
            title = (n.get("title") or "").strip()
            pub = (n.get("published") or "")[:10]
            lines.append(f"- [{pub}] ({src}) {title}")
        news_block = "\n\nBerita & headline terkini (live RSS feed):\n" + "\n".join(lines)
    return f"""Analisa aset berikut:
- Simbol: {symbol}
- Market: {market_name}
- Timeframe analisa: {timeframe}
- Harga saat ini: {price}
- Indikator teknikal terhitung:
  - RSI(14): {ta.get('rsi')}
  - EMA20: {ta.get('ema20')}
  - EMA50: {ta.get('ema50')}
  - MACD histogram: {ta.get('macd_hist')}
  - ATR(14): {ta.get('atr')}
- Sinyal rule-based saat ini: {ta.get('action')} ({ta.get('label')}) confidence {ta.get('confidence')}%
- Alasan teknis: {'; '.join(ta.get('reasons', []))}{news_block}

Pertimbangkan berita di atas (jika ada) bersama konteks makro & berita global/Indonesia terkini (kebijakan Fed, suku bunga BI, geopolitik, regulasi crypto, kondisi politik & ekonomi Indonesia) yang Anda ketahui.

Berikan rekomendasi trading. Balas HANYA dengan JSON sesuai skema ini:
{JSON_SCHEMA}
"""


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


async def _call_one(model_cfg: dict[str, str], prompt: str, session_id: str) -> dict[str, Any]:
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")

    async def _try(provider: str, model: str, label: str) -> tuple[bool, dict[str, Any]]:
        try:
            chat = LlmChat(
                api_key=api_key,
                session_id=session_id,
                system_message=SYSTEM_PROMPT,
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


def _aggregate(results: list[dict[str, Any]], fallback_ta: dict[str, Any]) -> dict[str, Any]:
    valid = [r["data"] for r in results if r.get("ok") and isinstance(r.get("data"), dict)]
    if not valid:
        return {
            "action": fallback_ta.get("action", "HOLD"),
            "label": fallback_ta.get("label", "HOLD"),
            "confidence": fallback_ta.get("confidence", 50),
            "summary": "Tidak ada respons valid dari model AI. Menampilkan sinyal teknikal saja.",
            "entry": fallback_ta.get("entry"),
            "stop_loss": fallback_ta.get("stop_loss"),
            "take_profit": fallback_ta.get("take_profit"),
            "timeframe_view": "Berdasarkan indikator teknikal lokal.",
            "news_factors": [],
            "risk_factors": ["Data AI tidak tersedia"],
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
        "summary": summaries[0] if summaries else "Konsensus model AI.",
        "entry": _avg(entries) or fallback_ta.get("entry"),
        "stop_loss": _avg(sls) or fallback_ta.get("stop_loss"),
        "take_profit": _avg(tps) or fallback_ta.get("take_profit"),
        "timeframe_view": timeframe_views[0] if timeframe_views else "",
        "news_factors": news_dedup[:6],
        "risk_factors": risks_dedup[:5],
        "votes": action_votes,
    }


async def ensemble_analyze(symbol: str, market: str, timeframe: str, ta: dict[str, Any], price: float, news: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run all three models concurrently and aggregate.

    `news` is a list of recent headlines (from RSS feed) which is injected
    into the prompt so the AI grounds its analysis on real-time events.
    """
    prompt = _build_prompt(symbol, market, timeframe, ta, price, news)
    session_base = f"{symbol}-{timeframe}-{uuid.uuid4().hex[:8]}"
    tasks = [
        _call_one(cfg, prompt, f"{session_base}-{cfg['provider']}")
        for cfg in MODELS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    fallback = dict(ta)
    fallback["_is_crypto"] = (market == "crypto")
    consensus = _aggregate(results, fallback)
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
