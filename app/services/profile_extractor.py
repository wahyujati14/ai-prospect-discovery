import asyncio
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import httpx

from app.schemas import RawCandidate, SocialLink
from app.utils.normalizers import canonicalize_profile_url
from app.utils.validators import (
    extract_valid_emails,
    extract_valid_phones,
    extract_whatsapp_links,
    is_safe_public_url,
    validate_email,
    validate_phone,
)

logger = logging.getLogger(__name__)

SOCIAL_ENRICH_PLATFORMS = {"LinkedIn", "Instagram", "X", "Facebook", "YouTube", "Threads", "WhatsApp"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MAX_HTML_BYTES = 750 * 1024


def extract_links_and_contacts_from_html(html: str, base_url: str) -> list[SocialLink]:
    soup = BeautifulSoup(html, "lxml")
    discovered: list[SocialLink] = []
    seen: set[tuple[str, str]] = set()

    def _add(platform: str, link: str) -> None:
        key = (platform, link.lower())
        if key not in seen:
            seen.add(key)
            discovered.append(SocialLink(platform=platform, link=link))

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href:
            continue
        lower = href.lower()
        if lower.startswith("mailto:"):
            valid_mail = validate_email(href)
            if valid_mail:
                _add("Email", valid_mail)
            continue
        if lower.startswith("tel:"):
            valid_tel = validate_phone(href)
            if valid_tel:
                _add("Phone", valid_tel)
            continue

        resolved = urljoin(base_url, href)
        canon = canonicalize_profile_url(resolved)
        if canon and canon[0] in SOCIAL_ENRICH_PLATFORMS:
            _add(canon[0], canon[1])

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    visible_text = soup.get_text(" ", strip=True)[:25000]

    for mail in extract_valid_emails(visible_text)[:3]:
        _add("Email", mail)
    for wa in extract_whatsapp_links(visible_text)[:2]:
        _add("WhatsApp", wa)
    for tel in extract_valid_phones(visible_text)[:2]:
        _add("Phone", tel)

    return discovered


async def enrich_website_candidates(
    candidates: list[RawCandidate],
    max_sites: int = 5,
    timeout_seconds: float = 8.0,
) -> None:
    """Fetch standalone public websites to discover verified contact & social links."""
    website_targets = [c for c in candidates if c.platform == "Google"][:max_sites]
    if not website_targets:
        return

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

    async def _fetch_one(client: httpx.AsyncClient, candidate: RawCandidate) -> None:
        if not is_safe_public_url(candidate.profile_url):
            return
        try:
            async with client.stream("GET", candidate.profile_url) as resp:
                if resp.status_code >= 400:
                    return
                ctype = (resp.headers.get("content-type") or "").lower()
                if ctype and "html" not in ctype:
                    return
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_HTML_BYTES:
                        break
                html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
        except Exception as exc:
            logger.debug("Skipping enrichment for %s: %s", candidate.profile_url, exc)
            return

        found = extract_links_and_contacts_from_html(html, candidate.profile_url)
        existing = {(s.platform, s.link.lower()) for s in candidate.extra_links}
        for item in found:
            if (item.platform, item.link.lower()) not in existing:
                existing.add((item.platform, item.link.lower()))
                candidate.extra_links.append(item)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=True,
        headers=headers,
    ) as client:
        await asyncio.gather(*(_fetch_one(client, c) for c in website_targets))
