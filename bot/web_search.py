import logging

import httpx

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


async def tavily_search(query: str, api_key: str, max_results: int = 3) -> str:
    """Run a Tavily web search and return a compact text summary."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                TAVILY_SEARCH_URL,
                json={
                    "query": query,
                    "api_key": api_key,
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Prefer Tavily's built-in answer if available
        if data.get("answer"):
            return data["answer"]

        # Fallback: concatenate result snippets
        parts = []
        for r in data.get("results", []):
            title = r.get("title", "")
            content = r.get("content", "")
            parts.append(f"- {title}: {content}")
        return "\n".join(parts) if parts else "Nessun risultato trovato."
    except Exception as e:
        logger.error("Tavily search error: %s", e)
        return f"Errore nella ricerca web: {e}"
