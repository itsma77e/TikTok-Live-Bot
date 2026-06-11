"""Behavioural settings editable from the dashboard and persisted to disk.

These are the knobs a non-technical operator changes at runtime (persona prompt,
which AI/voice to use, whether to thank followers/gifts). They live in
`data/settings.json` so a change survives a restart, while a fresh clone — which
has no `data/` dir — transparently falls back to the factory defaults in
config.py. Secrets (API keys) stay in `.env` and are deliberately NOT here.
"""

import json
import logging
import os
import tempfile
from dataclasses import dataclass, asdict

from config import settings
from bot.ai_provider import DEFAULT_MODEL_ID

logger = logging.getLogger(__name__)


@dataclass
class RuntimeConfig:
    system_prompt: str
    # Catalog id of the chosen model (see ai_provider.MODEL_CATALOG). The
    # provider is derived from it under the hood — the user only ever picks a
    # model, never a provider.
    model_id: str
    tts_voice: str
    thank_followers: bool
    thank_gifts: bool
    # The user's OpenAI key, pasted in the dashboard. Stored here (gitignored
    # data/ dir, never the repo) rather than in .env so a non-technical user
    # never has to edit a file. Seeded from .env on first run for back-compat.
    openai_api_key: str = ""
    # Tavily key — enables the web_search tool. Same UI-managed storage as the
    # OpenAI key; empty -> web search simply isn't offered to the model.
    tavily_api_key: str = ""


def _path() -> str:
    # Sibling of the memory store, under the same gitignored `data/` dir.
    base = os.path.dirname(settings.memory_dir) or "."
    return os.path.join(base, "settings.json")


def _defaults() -> RuntimeConfig:
    return RuntimeConfig(
        system_prompt=settings.system_prompt,
        model_id=DEFAULT_MODEL_ID,
        tts_voice=settings.tts_voice,
        thank_followers=settings.thank_followers,
        thank_gifts=settings.thank_gifts,
        openai_api_key=settings.openai_api_key,
        tavily_api_key=settings.tavily_api_key,
    )


def load() -> RuntimeConfig:
    """Factory defaults from config.py, overridden by data/settings.json if it
    exists. A missing or corrupt file never crashes startup — we fall back to
    the defaults so the bot always boots."""
    cfg = _defaults()
    path = _path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return cfg
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Could not read %s, using defaults: %s", path, e)
        return cfg

    if not isinstance(data, dict):
        logger.error("%s is not a JSON object, using defaults", path)
        return cfg

    # Only known fields are applied; unknown keys are ignored so an old or
    # hand-edited file can't break the load.
    for name in cfg.__dataclass_fields__:
        if name in data:
            setattr(cfg, name, data[name])
    return cfg


def save(cfg: RuntimeConfig) -> None:
    """Persist atomically: write to a temp file then os.replace, so a crash
    mid-write never leaves a half-written settings.json that fails to parse."""
    path = _path()
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
