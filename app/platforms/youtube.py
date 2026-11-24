import logging
import httpx

from app.platforms.base import PlatformAdapter
from app.schemas import ParsedQuery, RawCandidate, SocialLink
from app.utils.validators import extract_valid_emails, extract_whatsapp_links

logger = logging.getLogger(__name__)


class YouTubePlatform(PlatformAdapter):
    platform_name = "YouTube"

    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        loc = parsed.location.city or parsed.location.country or ""
        return [
            f'site:youtube.com/@ "{parsed.interest}" "{loc}"'.strip(),
        ]

    async def search_official_api(
        self,
        parsed: ParsedQuery,
        api_key: str,
        timeout_seconds: float = 10.0,
    ) -> list[RawCandidate]:
        if not api_key.strip():
            return []

        loc = parsed.location.display_label()
        q = f"{parsed.audience or parsed.interest} {loc}".strip()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={
                        "part": "snippet",
                        "type": "channel",
                        "maxResults": 5,
                        "q": q,
                        "key": api_key.strip(),
                    },
                )
                if resp.status_code != 200:
                    logger.warning("YouTube API returned HTTP %s", resp.status_code)
                    return []
                payload = resp.json()
        except Exception as exc:
            logger.warning("YouTube API lookup failed: %s", exc)
            return []

        candidates: list[RawCandidate] = []
        for item in payload.get("items", []):
            channel_id = item.get("id", {}).get("channelId") or item.get("snippet", {}).get("channelId")
            snippet = item.get("snippet", {})
            title = str(snippet.get("title", "")).strip()
            desc = str(snippet.get("description", "")).strip()
            if not channel_id or not title:
                continue

            profile_url = f"https://www.youtube.com/channel/{channel_id}"
            extra: list[SocialLink] = [
                SocialLink(platform="Email", link=m) for m in extract_valid_emails(desc)
            ]
            extra.extend(
                SocialLink(platform="WhatsApp", link=w) for w in extract_whatsapp_links(desc)
            )
            candidates.append(
                RawCandidate(
                    name=title,
                    platform="YouTube",
                    profile_url=profile_url,
                    handle=channel_id,
                    location=loc,
                    snippet=desc,
                    source_url=profile_url,
                    extra_links=extra,
                )
            )
        return candidates
