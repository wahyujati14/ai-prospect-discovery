from app.platforms.base import PlatformAdapter
from app.schemas import ParsedQuery, RawCandidate, SocialLink
from app.utils.normalizers import canonicalize_profile_url, clean_prospect_name, is_likely_prospect_name
from app.utils.validators import extract_valid_emails, extract_whatsapp_links


class WhatsAppPlatform(PlatformAdapter):
    platform_name = "WhatsApp"

    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        loc = parsed.location.city or parsed.location.country or ""
        return [
            f'("wa.me/" OR "api.whatsapp.com/send") "{parsed.interest}" "{loc}"'.strip(),
        ]

    def parse_search_item(self, item: dict[str, str], parsed_query: ParsedQuery) -> RawCandidate | None:
        raw_url = item.get("link", "").strip()
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        combined = f"{raw_url} {title} {snippet}"

        wa_links = extract_whatsapp_links(combined)
        if not wa_links:
            return None

        name = clean_prospect_name(title)
        if not is_likely_prospect_name(name):
            return None

        extra: list[SocialLink] = []
        canon = canonicalize_profile_url(raw_url)
        if canon and canon[0] != "WhatsApp":
            extra.append(SocialLink(platform=canon[0], link=canon[1]))

        for mail in extract_valid_emails(combined):
            extra.append(SocialLink(platform="Email", link=mail))

        primary_wa = wa_links[0]
        digits = primary_wa.rsplit("/", 1)[-1]
        return RawCandidate(
            name=name,
            platform="WhatsApp",
            profile_url=primary_wa,
            handle=digits,
            location=parsed_query.location.display_label(),
            snippet=snippet,
            source_url=raw_url,
            extra_links=extra,
        )
