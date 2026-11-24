import asyncio
import logging
import re

from ddgs import DDGS
import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


def _simplify_for_public_search(query: str) -> str:
    """Convert Google-specific dork operators into plain terms for public metasearch."""
    q = re.sub(r"-\S+", " ", query)
    q = re.sub(r"\bsite:([^\s)]+)", r"\1", q)
    q = re.sub(r"\bOR\b", " ", q)
    q = q.replace("(", " ").replace(")", " ").replace('"', " ")
    return " ".join(q.split())


class SearchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sem = asyncio.Semaphore(max(1, settings.max_concurrent_searches))

    async def search(self, query: str, max_results: int = 8) -> list[dict[str, str]]:
        async with self._sem:
            if self.settings.serper_api_key.strip():
                items = await self._search_serper(query, max_results)
                if items:
                    return items

            if self.settings.google_cse_api_key.strip() and self.settings.google_cse_cx.strip():
                items = await self._search_google_cse(query, max_results)
                if items:
                    return items

            return await self._search_ddgs(query, max_results)

    async def _search_serper(self, query: str, max_results: int) -> list[dict[str, str]]:
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={
                        "X-API-KEY": self.settings.serper_api_key.strip(),
                        "Content-Type": "application/json",
                    },
                    json={"q": query, "num": max_results},
                )
                if resp.status_code != 200:
                    logger.warning("Serper HTTP %s for query '%s'", resp.status_code, query)
                    return []
                payload = resp.json()
        except Exception as exc:
            logger.warning("Serper search error: %s", exc)
            return []

        return [
            {
                "title": str(row.get("title", "")),
                "link": str(row.get("link", "")),
                "snippet": str(row.get("snippet", "")),
            }
            for row in payload.get("organic", [])
            if row.get("link")
        ]

    async def _search_google_cse(self, query: str, max_results: int) -> list[dict[str, str]]:
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                resp = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": self.settings.google_cse_api_key.strip(),
                        "cx": self.settings.google_cse_cx.strip(),
                        "q": query,
                        "num": min(max_results, 10),
                    },
                )
                if resp.status_code != 200:
                    logger.warning("Google CSE HTTP %s", resp.status_code)
                    return []
                payload = resp.json()
        except Exception as exc:
            logger.warning("Google CSE search error: %s", exc)
            return []

        return [
            {
                "title": str(row.get("title", "")),
                "link": str(row.get("link", "")),
                "snippet": str(row.get("snippet", "")),
            }
            for row in payload.get("items", [])
            if row.get("link")
        ]

    async def _search_ddgs(self, query: str, max_results: int) -> list[dict[str, str]]:
        fallback_q = _simplify_for_public_search(query)

        def _sync_lookup() -> list[dict[str, str]]:
            with DDGS() as ddgs:
                raw_rows = list(ddgs.text(fallback_q, max_results=max_results, backend="auto"))
            out: list[dict[str, str]] = []
            for row in raw_rows:
                href = str(row.get("href") or row.get("link") or "").strip()
                if not href:
                    continue
                out.append(
                    {
                        "title": str(row.get("title", "")),
                        "link": href,
                        "snippet": str(row.get("body") or row.get("snippet") or ""),
                    }
                )
            return out

        try:
            return await asyncio.to_thread(_sync_lookup)
        except Exception as exc:
            logger.warning("Public search fallback failed for '%s': %s", query, exc)
            return []
