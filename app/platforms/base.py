from abc import ABC, abstractmethod

from app.schemas import ParsedQuery, RawCandidate, SocialLink
from app.utils.normalizers import (
    canonicalize_profile_url,
    clean_prospect_name,
    is_likely_prospect_name,
)
from app.utils.validators import (
    extract_valid_emails,
    extract_valid_phones,
    extract_whatsapp_links,
)


class PlatformAdapter(ABC):
    platform_name: str = ""

    @abstractmethod
    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        raise NotImplementedError

    def parse_search_item(self, item: dict[str, str], parsed_query: ParsedQuery) -> RawCandidate | None:
        raw_url = item.get("link", "").strip()
        canon = canonicalize_profile_url(raw_url)
        if not canon:
            return None

        platform, profile_url, handle = canon

        title = item.get("title", "")
        snippet = item.get("snippet", "")
        name = clean_prospect_name(title, handle=handle)
        if not is_likely_prospect_name(name):
            return None

        combined_text = f"{title} {snippet}"
        extra: list[SocialLink] = []
        for mail in extract_valid_emails(combined_text):
            extra.append(SocialLink(platform="Email", link=mail))
        for wa in extract_whatsapp_links(combined_text):
            if wa != profile_url:
                extra.append(SocialLink(platform="WhatsApp", link=wa))
        for tel in extract_valid_phones(combined_text):
            extra.append(SocialLink(platform="Phone", link=tel))

        return RawCandidate(
            name=name,
            platform=platform,
            profile_url=profile_url,
            handle=handle,
            location=parsed_query.location.display_label(),
            snippet=snippet,
            source_url=raw_url,
            extra_links=extra,
        )
