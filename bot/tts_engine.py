import asyncio
import logging
import tempfile
import os

import pygame

from bot.tts_backends import get_backend

logger = logging.getLogger(__name__)


class TTSEngine:
    def __init__(self, voice: str = "it-IT-ElsaNeural"):
        self.voice = voice
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None
        pygame.mixer.init()

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._worker())

    async def stop(self):
        self._running = False
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        pygame.mixer.quit()

    async def speak(self, text: str):
        logger.info("TTS queued: %s", text[:80])
        await self._queue.put(text)

    async def _worker(self):
        while self._running:
            try:
                text = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                continue

            tmp_path = None
            try:
                # Resolve the backend per item so a voice change between replies
                # takes effect immediately (and edge keeps working even if a
                # local model fails to load on a different item).
                backend = get_backend(self.voice)
                logger.info(
                    "TTS generating audio (%s) for: %s",
                    type(backend).__name__,
                    text[:80],
                )
                with tempfile.NamedTemporaryFile(
                    suffix=backend.suffix, delete=False
                ) as tmp:
                    tmp_path = tmp.name

                await backend.synth(text, tmp_path)
                file_size = os.path.getsize(tmp_path)
                logger.info("TTS audio saved: %s (%d bytes)", tmp_path, file_size)

                if file_size == 0:
                    logger.error("TTS generated empty audio file")
                    continue

                logger.info("TTS playing audio...")
                await self._play_audio(tmp_path)
                logger.info("TTS playback finished")
            except Exception as e:
                logger.error("TTS error: %s", e, exc_info=True)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    async def _play_audio(self, path: str):
        def _play():
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)

        await asyncio.to_thread(_play)
