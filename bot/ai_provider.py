import json
import logging
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from openai import AsyncOpenAI

from bot.web_search import tavily_search

logger = logging.getLogger(__name__)

# One past exchange = (username, message, response). Shared across the whole
# chat so the bot can answer "what did someone just ask you?" coherently.
HistoryEntry = tuple[str, str, str]

# Searches long-term memory. (query, username|None, recent) -> results string.
# recent=True sorts by time (newest first) instead of semantic relevance.
RecallFn = Callable[[str, "str | None", bool], Awaitable[str]]


def _build_messages(
    system_prompt: str,
    message: str,
    username: str,
    history: list[HistoryEntry] | None,
) -> list[dict]:
    """Assemble the chat-completions message list: system prompt, prior
    exchanges (oldest first), then the current message. Centralized so both
    providers format the [username] prefix identically."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for past_user, past_msg, past_resp in history or []:
        messages.append({"role": "user", "content": f"[{past_user}]: {past_msg}"})
        messages.append({"role": "assistant", "content": past_resp})
    messages.append({"role": "user", "content": f"[{username}]: {message}"})
    return messages

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information on any topic. "
            "Use when the user explicitly asks to search the web "
            "(e.g. 'cerca sul web', 'cercami', 'cosa dice internet su')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query in the language most likely to give good results",
                },
            },
            "required": ["query"],
        },
    },
}

RECALL_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": (
            "Search the bot's long-term memory of everything said across past "
            "live streams (including days ago). Use when the user references "
            "something said before, asks what was previously asked/said, or "
            "when prior context is needed to answer accurately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look for, in natural language",
                },
                "username": {
                    "type": "string",
                    "description": (
                        "Optional. Filters by the AUTHOR of the message (who "
                        "wrote it), NOT by who is mentioned. Use it only for "
                        "'what did X say / X's last message'. Do NOT set it "
                        "when looking for FACTS about a person (e.g. 'what "
                        "color is X's car', 'what does X do') — that info may "
                        "have been stated by someone else; instead put the "
                        "name in the query and search globally (no username)."
                    ),
                },
                "recent": {
                    "type": "boolean",
                    "description": (
                        "Set true when the user asks for the most RECENT or "
                        "LAST message(s) (e.g. 'ultimo messaggio', 'cosa ha "
                        "appena detto', 'qual è stata l'ultima domanda'): "
                        "results come back newest-first by time instead of by "
                        "relevance. Leave false/absent for topic searches "
                        "('cosa ha detto su X')."
                    ),
                },
            },
            "required": ["query"],
        },
    },
}

# Safety cap on tool round-trips so a model that keeps calling tools can't loop
# forever. After this many rounds we force a tool-free answer.
MAX_TOOL_ROUNDS = 3


class AIResponse:
    __slots__ = ("text", "web_search", "recall", "tool_log")

    def __init__(
        self,
        text: str,
        web_search: bool = False,
        recall: bool = False,
        tool_log: list[str] | None = None,
    ):
        self.text = text
        self.web_search = web_search
        self.recall = recall
        # Human-readable summary of each tool call (query, mode, result count),
        # surfaced in the dashboard so the operator can see what the bot did.
        self.tool_log = tool_log or []


def _summarize_tool_call(name: str, args: dict, result: str) -> str:
    """One-line, operator-facing summary of a tool call and its outcome."""
    no_hits = (not result) or result.startswith("Nessun risultato")
    if name == "recall_memory":
        q = args.get("query", "")
        who = f" @{args['username']}" if args.get("username") else ""
        mode = "recenti" if args.get("recent") else "rilevanza"
        n = 0 if no_hits else len(result.splitlines())
        return f"memoria: «{q}»{who} · {mode} · {n} risultati"
    if name == "web_search":
        return f"web: «{args.get('query', '')}»" + (" · 0 risultati" if no_hits else "")
    return name


async def _run_with_tools(
    client,
    model: str,
    messages: list[dict],
    tools: list[dict],
    dispatch: Callable[[str, dict], Awaitable[str]],
) -> tuple[str, bool, bool, list[str]]:
    """Drive a chat completion that may call tools. Loops, executing every
    requested tool and feeding results back, until the model answers or the
    round cap is hit. Returns (answer_text, web_search_used, recall_used,
    tool_log). Shared by both providers — they differ only in client + model."""
    web_used = False
    recall_used = False
    tool_log: list[str] = []
    for _ in range(MAX_TOOL_ROUNDS):
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools or None,
            max_tokens=200,
            temperature=0.8,
        )
        choice = resp.choices[0]
        if not (choice.finish_reason == "tool_calls" and choice.message.tool_calls):
            return choice.message.content or "", web_used, recall_used, tool_log

        # OpenAI requires the assistant message (with tool_calls) followed by
        # one tool message per tool_call_id, in order.
        messages.append(choice.message)
        for tc in choice.message.tool_calls:
            name = tc.function.name
            web_used = web_used or name == "web_search"
            recall_used = recall_used or name == "recall_memory"
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await dispatch(name, args)
            tool_log.append(_summarize_tool_call(name, args, result))
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result}
            )

    # Round cap reached: force a final answer without tools.
    final = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=200, temperature=0.8
    )
    return final.choices[0].message.content or "", web_used, recall_used, tool_log


class AIProvider(ABC):
    @abstractmethod
    async def generate_response(
        self,
        username: str,
        message: str,
        system_prompt: str,
        history: list[HistoryEntry] | None = None,
    ) -> AIResponse: ...


class _ToolChatProvider(AIProvider):
    """Shared base: OpenAI (cloud) and Ollama (local) both expose the same
    chat-completions + tools interface, so the only per-provider differences
    are the client and the model name."""

    def __init__(self, client, model: str, tavily_key: str, recall_fn: RecallFn | None):
        self._client = client
        self._model = model
        self._tavily_key = tavily_key
        self._recall_fn = recall_fn

    def _tools(self) -> list[dict]:
        tools = []
        if self._tavily_key:
            tools.append(WEB_SEARCH_TOOL)
        if self._recall_fn:
            tools.append(RECALL_MEMORY_TOOL)
        return tools

    async def _dispatch(self, name: str, args: dict) -> str:
        if name == "web_search" and self._tavily_key:
            return await tavily_search(args.get("query", ""), self._tavily_key)
        if name == "recall_memory" and self._recall_fn:
            res = await self._recall_fn(
                args.get("query", ""),
                args.get("username"),
                bool(args.get("recent", False)),
            )
            return res or "Nessun risultato pertinente nella memoria."
        return ""

    async def generate_response(
        self,
        username: str,
        message: str,
        system_prompt: str,
        history: list[HistoryEntry] | None = None,
    ) -> AIResponse:
        messages = _build_messages(system_prompt, message, username, history)
        try:
            text, web_used, recall_used, tool_log = await _run_with_tools(
                self._client, self._model, messages, self._tools(), self._dispatch
            )
            return AIResponse(
                text, web_search=web_used, recall=recall_used, tool_log=tool_log
            )
        except Exception as e:
            logger.error("%s error: %s", type(self).__name__, e)
            return AIResponse("", tool_log=[f"errore provider: {e}"])


class OpenAIProvider(_ToolChatProvider):
    def __init__(self, api_key: str, tavily_key: str = "", recall_fn: RecallFn | None = None):
        super().__init__(AsyncOpenAI(api_key=api_key), "gpt-4o-mini", tavily_key, recall_fn)


class OllamaProvider(_ToolChatProvider):
    """Local model via Ollama's OpenAI-compatible endpoint. Same chat+tools
    interface as the cloud providers, so it reuses the shared base — only the
    base_url, dummy key and model name differ."""

    def __init__(
        self,
        base_url: str,
        model: str,
        tavily_key: str = "",
        recall_fn: RecallFn | None = None,
    ):
        # Ollama ignores the API key but the SDK requires a non-empty value.
        super().__init__(
            AsyncOpenAI(base_url=base_url, api_key="ollama"), model, tavily_key, recall_fn
        )


# Single user-facing catalog of selectable models. The dashboard shows one
# "Modello" dropdown built from this list — the user never picks a provider, we
# derive it here under the hood. `needs_key` flags the cloud models that require
# the user's OpenAI key. Local (Ollama) models are the free/advanced tier and
# must be pulled first with `ollama pull <model>`. Order = display order.
MODEL_CATALOG = [
    {
        "id": "openai-gpt-4o-mini",
        "label": "GPT-4o mini · cloud, consigliato",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "needs_key": True,
    },
    {
        "id": "ollama-llama31-8b",
        "label": "Llama 3.1 8B · locale gratis (~8 GB RAM)",
        "provider": "ollama",
        "model": "llama3.1:8b",
        "needs_key": False,
    },
    {
        "id": "ollama-qwen25-7b",
        "label": "Qwen 2.5 7B · locale gratis, tool affidabili (~7 GB)",
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "needs_key": False,
    },
    {
        "id": "ollama-gemma3-4b",
        "label": "Gemma 3 4B · locale gratis, leggero (~4 GB)",
        "provider": "ollama",
        "model": "gemma3:4b",
        "needs_key": False,
    },
]
DEFAULT_MODEL_ID = MODEL_CATALOG[0]["id"]
_MODELS_BY_ID = {m["id"]: m for m in MODEL_CATALOG}


def resolve_model(model_id: str) -> dict:
    """Map a catalog id to its entry, falling back to the default so an unknown
    or stale id can never leave the bot without a usable model."""
    return _MODELS_BY_ID.get(model_id) or _MODELS_BY_ID[DEFAULT_MODEL_ID]


def get_provider(
    name: str,
    openai_key: str = "",
    tavily_key: str = "",
    recall_fn: RecallFn | None = None,
    ollama_base_url: str = "",
    ollama_model: str = "",
) -> AIProvider:
    if name == "ollama":
        return OllamaProvider(
            base_url=ollama_base_url,
            model=ollama_model,
            tavily_key=tavily_key,
            recall_fn=recall_fn,
        )
    return OpenAIProvider(api_key=openai_key, tavily_key=tavily_key, recall_fn=recall_fn)
