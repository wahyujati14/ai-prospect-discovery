import asyncio
from collections import OrderedDict
import logging
import time

from app.config import Settings
from app.platforms.base import PlatformAdapter
from app.platforms.facebook import FacebookPlatform
from app.platforms.google import GooglePlatform
from app.platforms.instagram import InstagramPlatform
from app.platforms.linkedin import LinkedInPlatform
from app.platforms.threads import ThreadsPlatform
from app.platforms.whatsapp import WhatsAppPlatform
from app.platforms.x_platform import XPlatform
from app.platforms.youtube import YouTubePlatform
from app.schemas import ProspectDiscoveryResponse, RawCandidate
from app.services.deduplication_service import build_prospect_records, consolidate_candidates
from app.services.llm_service import LLMClient
from app.services.profile_extractor import enrich_website_candidates
from app.services.query_service import QueryService
from app.services.relevance_service import filter_relevant_candidates
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)
MAX_CACHE_SIZE = 128


class ProspectDiscoveryService:
    def __init__(
        self,
        settings: Settings,
        llm_client: LLMClient | None = None,
        search_service: SearchService | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm_client or LLMClient(settings)
        self.query_service = QueryService(self.llm)
        self.search_service = search_service or SearchService(settings)
        self.youtube_platform = YouTubePlatform()
        self.platforms: list[PlatformAdapter] = [
            GooglePlatform(),
            LinkedInPlatform(),
            XPlatform(),
            self.youtube_platform,
            InstagramPlatform(),
            WhatsAppPlatform(),
            FacebookPlatform(),
            ThreadsPlatform(),
        ]
        self._cache: OrderedDict[str, tuple[float, ProspectDiscoveryResponse]] = OrderedDict()

    def _get_cached(self, query_key: str) -> ProspectDiscoveryResponse | None:
        entry = self._cache.get(query_key)
        if not entry:
            return None
        expires_at, response = entry
        if time.monotonic() > expires_at:
            self._cache.pop(query_key, None)
            return None
        self._cache.move_to_end(query_key)
        return response

    def _put_cache(self, query_key: str, response: ProspectDiscoveryResponse) -> None:
        if self.settings.cache_ttl_seconds <= 0:
            return
        self._cache[query_key] = (time.monotonic() + self.settings.cache_ttl_seconds, response)
        self._cache.move_to_end(query_key)
        while len(self._cache) > MAX_CACHE_SIZE:
            self._cache.popitem(last=False)

    async def discover(self, raw_query: str) -> ProspectDiscoveryResponse:
        cache_key = raw_query.strip().lower()
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached.model_copy(update={"query": raw_query})

        parsed = await self.query_service.understand_query(raw_query)

        async def _run_adapter(adapter: PlatformAdapter) -> list[RawCandidate]:
            found: list[RawCandidate] = []
            for search_q in adapter.build_queries(parsed):
                rows = await self.search_service.search(search_q, max_results=6)
                for row in rows:
                    cand = adapter.parse_search_item(row, parsed)
                    if cand is not None:
                        found.append(cand)
            return found

        tasks = [_run_adapter(adapter) for adapter in self.platforms]
        if self.settings.youtube_api_key.strip():
            tasks.append(
                self.youtube_platform.search_official_api(
                    parsed=parsed,
                    api_key=self.settings.youtube_api_key,
                    timeout_seconds=self.settings.request_timeout_seconds,
                )
            )

        platform_batches = await asyncio.gather(*tasks, return_exceptions=True)
        raw_candidates: list[RawCandidate] = []
        for batch in platform_batches:
            if isinstance(batch, Exception):
                logger.warning("Platform task failed independently: %s", batch)
                continue
            raw_candidates.extend(batch)

        await enrich_website_candidates(
            raw_candidates,
            max_sites=self.settings.max_website_enrichments,
            timeout_seconds=min(self.settings.request_timeout_seconds, 8.0),
        )

        consolidated = consolidate_candidates(raw_candidates)
        relevant = await filter_relevant_candidates(
            raw_query=raw_query,
            parsed=parsed,
            candidates=consolidated,
            llm_client=self.llm,
        )
        # Re-run consolidation in case LLM normalized name variants to the exact same person
        final_merged = consolidate_candidates(relevant)
        prospects = build_prospect_records(final_merged)

        response = ProspectDiscoveryResponse(
            success=True,
            query=raw_query,
            total_prospects=len(prospects),
            prospects=prospects,
        )
        self._put_cache(cache_key, response)
        return response
