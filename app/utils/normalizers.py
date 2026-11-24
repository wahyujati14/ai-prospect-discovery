import re
from urllib.parse import parse_qs, urlparse, urlunparse

from app.utils.validators import is_search_engine_url, normalize_whatsapp_link


DIRECTORY_AND_NOISE_DOMAINS = (
    "wikipedia.org",
    "yelp.com",
    "tripadvisor.",
    "yellowpages.",
    "clutch.co",
    "goodfirms.co",
    "designrush.com",
    "sortlist.com",
    "trustpilot.com",
    "glassdoor.",
    "indeed.com",
    "crunchbase.com",
    "zoominfo.com",
    "rocketreach.co",
    "apollo.io",
    "contactout.com",
    "signalhire.com",
    "lusha.com",
    "hunter.io",
    "datanyze.com",
    "reddit.com",
    "quora.com",
    "pinterest.",
    "tiktok.com",
    "medium.com",
    "eventbrite.",
    "meetup.com",
    "forbes.com",
    "timeout.com",
)

X_RESERVED = {
    "home",
    "explore",
    "search",
    "hashtag",
    "i",
    "intent",
    "share",
    "login",
    "signup",
    "settings",
    "tos",
    "privacy",
    "messages",
    "notifications",
}

IG_RESERVED = {
    "p",
    "reel",
    "reels",
    "stories",
    "explore",
    "accounts",
    "about",
    "legal",
    "directory",
    "tv",
    "developer",
}

FB_RESERVED = {
    "pages",
    "groups",
    "events",
    "watch",
    "marketplace",
    "gaming",
    "login",
    "share",
    "sharer.php",
    "share.php",
    "photo.php",
    "permalink.php",
    "story.php",
    "hashtag",
    "public",
    "search",
    "help",
    "policies",
    "reel",
    "reels",
}

LISTICLE_PATTERNS = re.compile(
    r"^(?:top\s+\d+|best\s+\d+|\d+\s+best|\d+\s+top|list\s+of\b|how\s+to\b|what\s+is\b|directory\s+of\b|find\s+the\s+best\b)",
    re.I,
)


def canonicalize_profile_url(raw_url: str) -> tuple[str, str, str] | None:
    """Return (platform, canonical_url, handle_or_key) for valid public profile/site links."""
    if not raw_url:
        return None
    cleaned = raw_url.strip()
    wa = normalize_whatsapp_link(cleaned)
    if wa:
        digits = wa.rsplit("/", 1)[-1]
        return ("WhatsApp", wa, digits)

    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return None
    if is_search_engine_url(cleaned):
        return None

    host = parsed.hostname.lower().removeprefix("www.").removeprefix("m.")
    segments = [seg for seg in parsed.path.split("/") if seg]

    # LinkedIn
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        if len(segments) >= 2 and segments[0] in ("in", "company"):
            slug = segments[1].strip()
            if slug and slug.lower() not in ("dir", "login", "pub"):
                kind = segments[0]
                return ("LinkedIn", f"https://www.linkedin.com/{kind}/{slug}", slug.lower())
        return None

    # X / Twitter
    if host in ("x.com", "twitter.com", "mobile.twitter.com"):
        if not segments:
            return None
        handle = segments[0].lstrip("@")
        if not handle or handle.lower() in X_RESERVED:
            return None
        if re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
            return ("X", f"https://x.com/{handle}", handle.lower())
        return None

    # Instagram
    if host == "instagram.com":
        if not segments:
            return None
        handle = segments[0].lstrip("@")
        if not handle or handle.lower() in IG_RESERVED:
            return None
        if re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
            return ("Instagram", f"https://www.instagram.com/{handle}/", handle.lower())
        return None

    # Threads
    if host in ("threads.net", "threads.com"):
        if not segments:
            return None
        first = segments[0]
        if first.startswith("@") and len(first) > 1:
            handle = first[1:]
            if re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
                return ("Threads", f"https://www.threads.net/@{handle}", handle.lower())
        return None

    # YouTube
    if host in ("youtube.com", "youtu.be"):
        if host == "youtu.be" or not segments:
            return None
        first = segments[0]
        if first.startswith("@") and len(first) > 1:
            handle = first[1:]
            return ("YouTube", f"https://www.youtube.com/@{handle}", handle.lower())
        if first in ("channel", "c", "user") and len(segments) >= 2:
            slug = segments[1]
            return ("YouTube", f"https://www.youtube.com/{first}/{slug}", slug.lower())
        return None

    # Facebook
    if host == "facebook.com" or host.endswith(".facebook.com"):
        if not segments:
            return None
        first = segments[0]
        if first.lower() in FB_RESERVED:
            return None
        if first == "profile.php":
            uid = (parse_qs(parsed.query).get("id") or [""])[0].strip()
            if uid.isdigit():
                return ("Facebook", f"https://www.facebook.com/profile.php?id={uid}", uid)
            return None
        if first == "p" and len(segments) >= 2:
            slug = segments[1]
            return ("Facebook", f"https://www.facebook.com/p/{slug}", slug.lower())
        if re.fullmatch(r"[A-Za-z0-9.\-_]{2,80}", first):
            return ("Facebook", f"https://www.facebook.com/{first}", first.lower())
        return None

    # Public standalone website discovered via Google/search
    if any(noise in host for noise in DIRECTORY_AND_NOISE_DOMAINS):
        return None
    if parsed.path.lower().endswith((".pdf", ".xml", ".zip", ".doc", ".docx")):
        return None

    clean_path = "/" if not segments else "/" + "/".join(segments[:2])
    site_url = urlunparse(("https", parsed.hostname.lower(), clean_path, "", "", ""))
    return ("Google", site_url, host)


def clean_prospect_name(raw_title: str, handle: str = "") -> str:
    text = re.sub(r"\s+", " ", (raw_title or "")).strip()
    if not text:
        return handle

    # Remove trailing platform labels
    text = re.sub(
        r"\s*(?:\||-|•|–|—|/|:)\s*(?:LinkedIn|Instagram(?:\s+photos\s+and\s+videos)?|Facebook|YouTube|X|Twitter|Threads)\b.*$",
        "",
        text,
        flags=re.I,
    )
    # Remove (@handle) annotations in social titles
    text = re.sub(r"\s*\(@[A-Za-z0-9._]+\)\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" |-•–—:")

    # LinkedIn titles often look like "Name - Role - Company"; take the leading entity name
    if " - " in text:
        first_chunk = text.split(" - ", 1)[0].strip()
        if 2 <= len(first_chunk) <= 60:
            text = first_chunk
    elif " | " in text:
        first_chunk = text.split(" | ", 1)[0].strip()
        if 2 <= len(first_chunk) <= 60:
            text = first_chunk

    return text[:80].strip()


def is_likely_prospect_name(name: str) -> bool:
    cleaned = name.strip()
    if len(cleaned) < 2 or len(cleaned) > 75:
        return False
    if LISTICLE_PATTERNS.search(cleaned):
        return False
    lowered = cleaned.lower()
    blocked_exact = {
        "home",
        "about",
        "about us",
        "contact",
        "contact us",
        "login",
        "sign in",
        "search",
        "jobs",
        "careers",
        "blog",
        "news",
    }
    if lowered in blocked_exact:
        return False
    return True


def normalize_name_key(name: str) -> str:
    lowered = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    tokens = [t for t in lowered.split() if t not in {"mr", "mrs", "ms", "dr", "inc", "llc", "ltd", "co"}]
    return " ".join(tokens)
