"""TTS backend routing.

The dashboard stores the chosen voice as a single string key. That key decides
which engine actually synthesizes the audio:

  - "it-IT-ElsaNeural"      -> edge-tts (cloud, default, always available)
  - "supertonic:it:F1"      -> Supertonic 3 (local, on-device, CPU)

Each backend turns text into an audio file on disk. The TTS worker
(bot/tts_engine.py) owns the queue, temp-file lifecycle and playback; backends
only fill in the "text -> audio file" step. Keeping that boundary lets edge-tts
keep working untouched even if the local model fails to load.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

SUPERTONIC_PREFIX = "supertonic:"


class TTSBackend:
    # Container suffix the worker must use for the temp file it hands to synth().
    suffix = ".mp3"

    async def synth(self, text: str, out_path: str) -> None:
        raise NotImplementedError


class EdgeBackend(TTSBackend):
    """Microsoft Edge neural voices via edge-tts (the original engine)."""

    suffix = ".mp3"

    def __init__(self, voice: str):
        self.voice = voice

    async def synth(self, text: str, out_path: str) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(out_path)


class SupertonicBackend(TTSBackend):
    """Local on-device TTS (Supertone Supertonic 3, ONNX, CPU).

    The model is heavy to load (~3s) and the same instance serves every voice
    and language, so it is loaded once and shared across all backend instances
    via a class-level singleton. Loading is lazy: nothing touches the model (or
    downloads its ~400MB of weights) until a Supertonic voice is first used.
    """

    suffix = ".wav"

    _model = None
    _model_lock = asyncio.Lock()
    _styles: dict[str, object] = {}

    def __init__(self, lang: str, voice: str):
        self.lang = lang
        self.voice = voice

    @classmethod
    async def _get_model(cls):
        if cls._model is None:
            async with cls._model_lock:
                if cls._model is None:
                    logger.info("Loading Supertonic model (first use)...")
                    cls._model = await asyncio.to_thread(cls._load_model)
                    logger.info("Supertonic model ready")
        return cls._model

    @staticmethod
    def _load_model():
        # Imported lazily so the app runs without supertonic installed as long
        # as no Supertonic voice is selected.
        from supertonic import TTS

        return TTS(model="supertonic-3", auto_download=True)

    @classmethod
    def _get_style(cls, model, voice: str):
        # Voice styles are static JSON; cache them so we don't re-read on every
        # reply. Shared across instances since the styles are model-global.
        style = cls._styles.get(voice)
        if style is None:
            style = model.get_voice_style(voice)
            cls._styles[voice] = style
        return style

    async def synth(self, text: str, out_path: str) -> None:
        model = await self._get_model()
        style = self._get_style(model, self.voice)

        def _run():
            wav, _duration = model.synthesize(text, style, lang=self.lang)
            model.save_audio(wav, out_path)

        await asyncio.to_thread(_run)


def get_backend(voice: str) -> TTSBackend:
    """Resolve a dashboard voice key to the backend that should speak it."""
    if voice.startswith(SUPERTONIC_PREFIX):
        # "supertonic:<lang>:<voice>" e.g. "supertonic:it:F1"
        parts = voice.split(":")
        if len(parts) == 3:
            _, lang, name = parts
            return SupertonicBackend(lang, name)
        logger.warning("Malformed supertonic voice key %r, falling back to edge", voice)
    return EdgeBackend(voice)
