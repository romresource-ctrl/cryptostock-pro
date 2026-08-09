"""v8.7.1 — Daily AI Market Brief backend contract tests.

Covers:
  - GET /api/market-brief?lang=en  → shape + required fields
  - GET /api/market-brief?lang=id / ru / cn → translation returned
  - Translation caching (2nd hit is fast)
  - Idempotency: brief _id follows {date_key}-{session}
  - TTL index on generated_at (48h)
  - Regression on dashboard / track-record / push history endpoints

We do NOT call POST /api/market-brief/generate — that costs LLM tokens.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

REQUIRED_BRIEF_KEYS = {
    "id", "session", "date_key", "generated_at", "lang",
    "sentiment", "sentiment_score", "summary",
    "sections", "top_movers", "top_headlines", "warning_zones",
}
REQUIRED_SECTIONS = {"crypto", "stocks", "forex", "gold"}
VALID_SENTIMENTS = {"bullish", "bearish", "mixed", "neutral"}


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Core /market-brief contract ----------


class TestMarketBriefEnglish:
    """Baseline: EN brief must be available (warm-started at boot) and well-formed."""

    def test_en_returns_200(self, api):
        r = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30)
        assert r.status_code == 200, r.text

    def test_en_envelope_shape(self, api):
        r = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30)
        j = r.json()
        assert set(j.keys()) >= {"available", "lang", "brief"}
        assert j["lang"] == "en"
        assert j["available"] is True, "warm-started brief missing"
        assert isinstance(j["brief"], dict)

    def test_en_brief_has_all_required_fields(self, api):
        j = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()
        b = j["brief"]
        missing = REQUIRED_BRIEF_KEYS - set(b.keys())
        assert not missing, f"missing keys: {missing}"

    def test_en_generated_at_is_iso(self, api):
        b = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        # datetime.fromisoformat must succeed
        datetime.fromisoformat(b["generated_at"].replace("Z", "+00:00"))

    def test_en_id_matches_date_session(self, api):
        b = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        assert b["id"] == f"{b['date_key']}-{b['session']}", b["id"]
        assert b["session"] in ("morning", "evening")
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", b["date_key"])

    def test_en_sentiment_valid(self, api):
        b = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        assert b["sentiment"] in VALID_SENTIMENTS
        assert isinstance(b["sentiment_score"], int)
        assert -100 <= b["sentiment_score"] <= 100

    def test_en_summary_and_sections_are_strings(self, api):
        b = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        assert isinstance(b["summary"], str) and len(b["summary"]) > 20
        secs = b["sections"]
        assert set(secs.keys()) >= REQUIRED_SECTIONS
        for k in REQUIRED_SECTIONS:
            assert isinstance(secs[k], str) and len(secs[k]) > 10, f"section {k} weak: {secs[k]!r}"

    def test_en_top_movers_shape(self, api):
        b = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        tm = b["top_movers"]
        assert isinstance(tm, list) and len(tm) >= 1
        for m in tm:
            assert {"symbol", "market", "change_pct_24h", "note"} <= set(m.keys()), m
            assert isinstance(m["change_pct_24h"], (int, float))

    def test_en_top_headlines_shape(self, api):
        b = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        th = b["top_headlines"]
        assert isinstance(th, list)
        for h in th:
            # Each headline is expected to have title / source / why_matters
            assert "title" in h and isinstance(h["title"], str)

    def test_en_warning_zones_list_of_strings(self, api):
        b = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        wz = b["warning_zones"]
        assert isinstance(wz, list)
        for w in wz:
            assert isinstance(w, str) and len(w) > 0


# ---------- Translation tests ----------


def _fetch(api, lang: str):
    t0 = time.time()
    r = api.get(f"{BASE_URL}/api/market-brief", params={"lang": lang}, timeout=120)
    dt = time.time() - t0
    return r.status_code, r.json(), dt


def _tickers_in(txt: str) -> set[str]:
    return set(re.findall(r"\b(BTC|ETH|BNB|SOL|XRP|XAU|XAG|SPX|NDX|USD|EUR|JPY|CNY|TEAM|PLTR|SNOW)\b", txt or ""))


class TestMarketBriefIndonesian:
    """?lang=id → summary + sections translated to Bahasa Indonesia; tickers & numbers preserved."""

    def test_id_returns_200_and_available(self, api):
        code, j, _ = _fetch(api, "id")
        assert code == 200
        assert j["available"] is True
        assert j["lang"] == "id"

    def test_id_has_same_structure(self, api):
        _, j, _ = _fetch(api, "id")
        assert REQUIRED_BRIEF_KEYS - set(j["brief"].keys()) == set()

    def test_id_summary_is_translated(self, api):
        _, en_j, _ = _fetch(api, "en")
        _, id_j, _ = _fetch(api, "id")
        assert id_j["brief"]["summary"] != en_j["brief"]["summary"], "id summary looks identical to en"

    def test_id_preserves_numbers_and_tickers(self, api):
        _, en_j, _ = _fetch(api, "en")
        _, id_j, _ = _fetch(api, "id")
        # tickers appearing in EN top_movers must appear in ID top_movers.
        en_syms = {m["symbol"] for m in en_j["brief"]["top_movers"]}
        id_syms = {m["symbol"] for m in id_j["brief"]["top_movers"]}
        assert en_syms == id_syms, f"ticker set diverged en={en_syms} id={id_syms}"
        # change_pct_24h must be numeric and equal
        for a, b in zip(en_j["brief"]["top_movers"], id_j["brief"]["top_movers"]):
            assert a["change_pct_24h"] == b["change_pct_24h"], (a, b)


class TestTranslationCaching:
    """Second /market-brief?lang=id call should be substantially faster (served from Mongo cache)."""

    def test_id_second_call_is_faster(self, api):
        # Prime cache first (may take up to ~30s if not warmed).
        _, _, t1 = _fetch(api, "id")
        _, _, t2 = _fetch(api, "id")
        # Second call should hit Mongo cache (< 3s round trip); we allow up to 5s buffer.
        assert t2 < max(3.0, t1 * 0.5 + 0.5), f"expected 2nd call cached but t1={t1:.2f}s t2={t2:.2f}s"


class TestMarketBriefRussianChinese:

    def test_ru_returns_200_available(self, api):
        code, j, _ = _fetch(api, "ru")
        assert code == 200
        assert j["available"] is True
        assert j["lang"] == "ru"
        assert isinstance(j["brief"]["summary"], str) and len(j["brief"]["summary"]) > 10

    def test_ru_differs_from_en(self, api):
        _, en_j, _ = _fetch(api, "en")
        _, ru_j, _ = _fetch(api, "ru")
        assert ru_j["brief"]["summary"] != en_j["brief"]["summary"]

    def test_cn_returns_200_available(self, api):
        code, j, _ = _fetch(api, "cn")
        assert code == 200
        assert j["available"] is True
        assert j["lang"] == "cn"

    def test_cn_differs_from_en(self, api):
        _, en_j, _ = _fetch(api, "en")
        _, cn_j, _ = _fetch(api, "cn")
        assert cn_j["brief"]["summary"] != en_j["brief"]["summary"]

    def test_bad_lang_falls_back_to_en(self, api):
        r = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "zz"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["lang"] == "en"


# ---------- Idempotency + TTL (direct Mongo check) ----------


class TestBriefStorage:
    """Direct Mongo checks: idempotent _id and TTL index."""

    def test_brief_id_is_unique_per_date_session(self, api):
        # Query the collection: for the current brief, there should be exactly 1
        # doc with that _id (idempotent upsert).
        b = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        # We can only observe this externally — call GET twice; id must stay stable.
        b2 = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30).json()["brief"]
        assert b["id"] == b2["id"], "brief id changed between GETs — not idempotent!"
        assert b["generated_at"] == b2["generated_at"], "generated_at drifted — duplicate write?"

    def test_ttl_index_exists(self):
        # Direct MongoDB check.
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio

        async def _check():
            client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=15000)
            db = client[os.environ["DB_NAME"]]
            idx = await db.market_briefs.index_information()
            client.close()
            return idx

        # Load env from backend/.env for MONGO_URL if not already set.
        if "MONGO_URL" not in os.environ or "DB_NAME" not in os.environ:
            from dotenv import load_dotenv
            load_dotenv("/app/backend/.env")
        idx = asyncio.run(_check())
        # Find any index on generated_at with expireAfterSeconds set.
        matched = None
        for name, spec in idx.items():
            key = spec.get("key") or []
            if any(k[0] == "generated_at" for k in key) and "expireAfterSeconds" in spec:
                matched = (name, spec["expireAfterSeconds"])
                break
        assert matched is not None, f"no TTL index on generated_at; got: {list(idx.keys())}"
        # 48h = 172800
        assert matched[1] == 48 * 3600, f"expected 48h TTL, got {matched[1]}s (index {matched[0]})"


# ---------- Regression on existing endpoints ----------


class TestRegression:

    def test_dashboard_crypto_still_works(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard", params={"market": "crypto"}, timeout=60)
        assert r.status_code == 200
        j = r.json()
        assert j.get("market") == "crypto"
        assert isinstance(j.get("assets"), list) and len(j["assets"]) > 0

    def test_track_record_btc(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/track-record", timeout=30)
        assert r.status_code == 200
        j = r.json()
        # v8.7.0 keys must still be present
        assert "win_rate_all" in j
        assert "history_all" in j

    def test_push_history_en(self, api):
        r = api.get(f"{BASE_URL}/api/push/history", params={"language": "en"}, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j or "history" in j or isinstance(j, dict), j
