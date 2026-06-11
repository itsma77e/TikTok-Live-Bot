"""Persistent long-term memory with RAG.

Every chat message is stored append-only and embedded so the bot can recall,
across sessions and days, what was said. Two files kept in lockstep:

    messages.jsonl   one JSON record per line (human-readable, exportable)
    embeddings.f32   raw float32 vectors, fixed dim, concatenated

Row N of the binary file corresponds to line N of the JSONL. Appends happen in
a single synchronous block (no await in between) so the two files can never
drift within a single asyncio process. On load, a length mismatch (e.g. a crash
mid-write) is recovered by truncating to the shorter of the two.

Embeddings always go through OpenAI — the local provider has no equivalent here
— so this needs an OpenAI key even when the chat provider is local. No key ->
memory disabled.
"""

import json
import logging
import os
import time
from datetime import datetime

import numpy as np
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def read_messages(directory: str, limit: int | None = None) -> list[dict]:
    """Read stored memory entries straight from the JSONL, newest first.

    Independent of any running MemoryStore (no embeddings, no OpenAI key), so
    the dashboard can show saved memory even while the bot is stopped. A torn
    last line from a crash is skipped, not fatal.
    """
    path = os.path.join(directory, "messages.jsonl")
    records: list[dict] = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line while reading memory.")
                continue
    records.reverse()  # newest first
    if limit is not None:
        records = records[:limit]
    return records


class MemoryStore:
    def __init__(
        self,
        directory: str,
        openai_api_key: str,
        embedding_model: str,
        embedding_dims: int,
    ):
        self._dir = directory
        self._messages_path = os.path.join(directory, "messages.jsonl")
        self._embeddings_path = os.path.join(directory, "embeddings.f32")
        self._model = embedding_model
        self._dims = embedding_dims

        self._records: list[dict] = []
        # Per-row vectors appended O(1); the stacked matrix is rebuilt lazily on
        # search and cached until the next add invalidates it. Search (once per
        # /bot) is far rarer than add (once per comment), so paying the stack
        # cost at search time keeps adds cheap during a comment flood.
        self._vecs: list[np.ndarray] = []
        self._matrix: np.ndarray | None = None

        self.enabled = bool(openai_api_key)
        self._client = AsyncOpenAI(api_key=openai_api_key) if self.enabled else None
        if not self.enabled:
            logger.warning("Memory disabled: no OpenAI API key for embeddings.")

    # --- lifecycle ---

    def load(self) -> None:
        """Load existing store into memory. Recovers from a torn write by
        truncating both files to the shorter length."""
        if not self.enabled:
            return
        os.makedirs(self._dir, exist_ok=True)

        records: list[dict] = []
        if os.path.exists(self._messages_path):
            with open(self._messages_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            # Torn last line from a crash; stop reading here.
                            logger.warning("Skipping malformed JSONL line on load.")
                            break

        vectors = np.empty((0, self._dims), dtype=np.float32)
        if os.path.exists(self._embeddings_path):
            raw = np.fromfile(self._embeddings_path, dtype=np.float32)
            usable = (raw.size // self._dims) * self._dims
            vectors = raw[:usable].reshape(-1, self._dims)

        n = min(len(records), len(vectors))
        if len(records) != len(vectors):
            logger.warning(
                "Memory length mismatch (jsonl=%d, f32=%d); truncating to %d.",
                len(records),
                len(vectors),
                n,
            )
        self._records = records[:n]
        self._vecs = [vectors[i] for i in range(n)]
        self._matrix = None
        logger.info("Memory loaded: %d entries.", n)

    def clear(self) -> None:
        """Wipe all stored memory: both files and the in-memory state, so a
        running bot immediately stops recalling old entries (no restart needed)
        and the id counter restarts from zero."""
        for path in (self._messages_path, self._embeddings_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                logger.error("Could not delete %s: %s", path, e)
        self._records = []
        self._vecs = []
        self._matrix = None

    # --- write ---

    async def add(
        self,
        username: str,
        message: str,
        response: str = "",
        kind: str = "chat",
        session: str = "",
        ts: float | None = None,
    ) -> None:
        """Embed and persist one message. If embedding fails the entry is
        dropped entirely so the two files stay aligned.

        ts MUST be captured when the message arrived, not here: embedding runs
        in the background and finishes out of order, so a ts taken after the
        await would scramble chronological order and break 'last message'
        queries. Callers pass the arrival time."""
        if not self.enabled:
            return
        text = f"{message}\n{response}".strip() if response else message.strip()
        if not text:
            return

        vec = await self._embed(text)
        if vec is None:
            return  # never write a JSONL row without its vector

        if ts is None:
            ts = time.time()
        record = {
            "id": len(self._records),
            "ts": ts,
            "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
            "session": session,
            "username": username,
            "message": message,
            "response": response,
            "kind": kind,
        }

        # Critical section: no await between the two appends and the in-memory
        # update, so jsonl row N and f32 row N can never diverge.
        os.makedirs(self._dir, exist_ok=True)
        with open(self._messages_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        with open(self._embeddings_path, "ab") as f:
            f.write(vec.tobytes())
        self._records.append(record)
        self._vecs.append(vec)
        self._matrix = None

    # --- read ---

    async def recall(
        self,
        query: str,
        username: str | None = None,
        top_k: int = 4,
        recent: bool = False,
    ) -> str:
        """Search memory and return a formatted, model-readable string. Empty
        string when memory is off, empty, or nothing matches. With recent=True
        results are newest-first so the model can answer "last message" type
        questions; otherwise they're ordered by semantic relevance."""
        records = await self.search(
            query, top_k=top_k, username=username, recent=recent
        )
        if not records:
            return ""
        lines = []
        for r in records:
            who = r.get("username", "?")
            when = self._when(r)
            msg = r.get("message", "")
            resp = r.get("response", "")
            if resp:
                lines.append(f"[{when}] {who}: {msg} → bot: {resp}")
            else:
                lines.append(f"[{when}] {who}: {msg}")
        return "\n".join(lines)

    @staticmethod
    def _when(record: dict) -> str:
        """Date + time label. Time matters for 'last message' ordering on the
        same day; falls back to the stored date string if ts is missing."""
        ts = record.get("ts")
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        return record.get("date", "?")

    async def search(
        self,
        query: str,
        top_k: int = 4,
        username: str | None = None,
        recent: bool = False,
    ) -> list[dict]:
        if not self.enabled or not self._records:
            return []

        idx = list(range(len(self._records)))
        if username:
            # Substring match, not equality: TikTok handles are messy (prefixes,
            # emojis like "~alex" or "BarberPeter…🇦🇺") and the model often passes
            # a simplified name ("alex"). Exact match would silently find nothing.
            uname = username.lower().lstrip("@~ ").strip()
            idx = [
                i for i in idx
                if uname and uname in self._records[i].get("username", "").lower()
            ]
            if not idx:
                return []

        # Recency mode: temporal questions ("ultimo messaggio", "cosa ha appena
        # detto") can't be answered by similarity — sort by time, newest first.
        # No embedding needed, so it's also cheaper.
        if recent:
            idx.sort(key=lambda i: self._records[i].get("ts", 0.0), reverse=True)
            return [self._records[i] for i in idx[:top_k]]

        q = await self._embed(query)
        if q is None:
            return []
        matrix = self._get_matrix()
        sub = matrix[idx]
        # Cosine similarity: normalize rows and query, then dot product.
        sub_norm = sub / (np.linalg.norm(sub, axis=1, keepdims=True) + 1e-8)
        q_norm = q / (np.linalg.norm(q) + 1e-8)
        scores = sub_norm @ q_norm
        order = np.argsort(scores)[::-1][:top_k]
        return [self._records[idx[i]] for i in order]

    def _get_matrix(self) -> np.ndarray:
        if self._matrix is None:
            if self._vecs:
                self._matrix = np.stack(self._vecs)
            else:
                self._matrix = np.empty((0, self._dims), dtype=np.float32)
        return self._matrix

    async def _embed(self, text: str) -> np.ndarray | None:
        if not self._client:
            return None
        try:
            resp = await self._client.embeddings.create(
                model=self._model,
                input=text,
                dimensions=self._dims,
            )
            return np.asarray(resp.data[0].embedding, dtype=np.float32)
        except Exception as e:
            logger.error("Embedding error: %s", e)
            return None
