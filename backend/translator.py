"""Translate arbitrary text via Emergent LLM (Claude Haiku) with MongoDB caching.

Public API:
  translate_many(db, texts, target_lang) -> list[str]  (parallel, order preserved)

Cache key: sha256(text + "|" + target_lang). Hit returns instantly. Misses
batch-translate up to 20 texts per LLM call to minimize cost & latency.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from typing import Iterable

from emergentintegrations.llm.chat import LlmChat, UserMessage
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("translator")

# Use Claude Haiku for fast/cheap translations.
_MODEL_PROVIDER = "anthropic"
_MODEL_NAME = "claude-haiku-4-5"

# Batch up to this many texts in a single LLM call.
_BATCH_SIZE = 15


def _hash_key(text: str, target_lang: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    h.update(b"|")
    h.update(target_lang.encode("utf-8"))
    return h.hexdigest()


_LANG_NAME = {
    "en": "English",
    "id": "Indonesian (Bahasa Indonesia)",
}


async def _llm_translate_batch(items: list[str], target_lang: str) -> list[str]:
    """Translate a batch of strings via Claude Haiku. Returns same-length list."""
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        return items  # fail-open: return original
    target_label = _LANG_NAME.get(target_lang, target_lang)

    # Numbered list keeps order; we ask the model to return JSON for safety.
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(items))
    prompt = (
        f"Translate the following items into {target_label}. Keep the meaning, tone, and "
        f"any ticker symbols/prices/numbers untouched. Do NOT add commentary.\n"
        f"Return ONLY a JSON object exactly like {{\"items\": [\"translated 1\", \"translated 2\", ...]}} "
        f"with the same number of items in the same order.\n\nINPUT:\n{numbered}"
    )

    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"translate-{target_lang}",
            system_message="You are a precise translator. Always preserve numbers, ticker symbols, percentages, and product names.",
        ).with_model(_MODEL_PROVIDER, _MODEL_NAME)
        resp = await chat.send_message(UserMessage(text=prompt))
        text = resp if isinstance(resp, str) else str(resp)
        # extract JSON
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return items
        data = json.loads(m.group(0))
        arr = data.get("items") or []
        if not isinstance(arr, list) or len(arr) != len(items):
            return items
        return [str(x) for x in arr]
    except Exception as e:
        logger.warning("translate batch failed: %s", e)
        return items


async def translate_many(
    db: AsyncIOMotorDatabase,
    texts: Iterable[str],
    target_lang: str,
) -> list[str]:
    """Translate a list of strings, caching results in db.translations.

    Empty / whitespace strings pass through. If target_lang is "id" or "" or
    same as the source language, returns input unchanged.
    """
    items = list(texts)
    if not items or target_lang not in ("en",):
        return items

    keys = [_hash_key(t, target_lang) if t and t.strip() else "" for t in items]
    # Lookup cache
    found: dict[str, str] = {}
    cache_keys = [k for k in keys if k]
    if cache_keys:
        async for doc in db.translations.find({"_id": {"$in": cache_keys}}):
            found[doc["_id"]] = doc.get("translated", "")

    # Determine which are missing
    missing_idx: list[int] = []
    missing_texts: list[str] = []
    for i, (text, key) in enumerate(zip(items, keys)):
        if not key:
            continue
        if key not in found:
            missing_idx.append(i)
            missing_texts.append(text)

    if missing_texts:
        # Translate in chunks of _BATCH_SIZE
        translated_all: list[str] = []
        for start in range(0, len(missing_texts), _BATCH_SIZE):
            chunk = missing_texts[start:start + _BATCH_SIZE]
            translated_all.extend(await _llm_translate_batch(chunk, target_lang))

        # Persist
        writes = []
        for idx, translated in zip(missing_idx, translated_all):
            k = keys[idx]
            found[k] = translated
            writes.append({
                "_id": k,
                "source": items[idx],
                "target_lang": target_lang,
                "translated": translated,
            })
        try:
            if writes:
                # upsert in parallel
                await asyncio.gather(*[
                    db.translations.replace_one({"_id": w["_id"]}, w, upsert=True)
                    for w in writes
                ])
        except Exception as e:
            logger.warning("translation cache write failed: %s", e)

    # Build final list preserving order
    out: list[str] = []
    for text, key in zip(items, keys):
        if not key:
            out.append(text)
        else:
            out.append(found.get(key) or text)
    return out
