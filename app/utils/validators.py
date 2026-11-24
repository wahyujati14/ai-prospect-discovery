import ipaddress
import re
import socket
from urllib.parse import parse_qs, urlparse


EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,15}\b")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s().\-]{7,18}\d)")
WHATSAPP_URL_PATTERN = re.compile(
    r"https?://(?:wa\.me/\d{8,15}|api\.whatsapp\.com/send\?[^\s\"'<>]+)",
    re.I,
)

JUNK_EMAIL_DOMAINS = {
    "example.com",
    "domain.com",
    "yourdomain.com",
    "email.com",
    "test.com",
    "sentry.io",
    "wixpress.com",
    "cloudflare.com",
    "googleusercontent.com",
    "w3.org",
    "schema.org",
}

JUNK_EMAIL_PREFIXES = ("noreply@", "no-reply@", "donotreply@", "mailer-daemon@", "postmaster@")
ASSET_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".woff")

SEARCH_ENGINE_HOSTS = (
    "google.",
    "bing.com",
    "duckduckgo.com",
    "search.yahoo.com",
    "yandex.",
    "baidu.com",
)


def is_search_engine_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if any(token in host for token in SEARCH_ENGINE_HOSTS):
        return True
    if "/search" in parsed.path.lower() and ("q=" in parsed.query.lower() or "query=" in parsed.query.lower()):
        return True
    return False


def validate_email(raw_email: str) -> str | None:
    cleaned = raw_email.strip().strip(".,;:()[]<>\"'").lower()
    if cleaned.startswith("mailto:"):
        cleaned = cleaned[7:].split("?")[0].strip()

    if not EMAIL_PATTERN.fullmatch(cleaned):
        return None
    if cleaned.endswith(ASSET_EXTENSIONS) or cleaned.startswith(JUNK_EMAIL_PREFIXES):
        return None

    domain = cleaned.split("@", 1)[1]
    if domain in JUNK_EMAIL_DOMAINS or ".." in cleaned:
        return None
    return f"mailto:{cleaned}"


def extract_valid_emails(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in EMAIL_PATTERN.findall(text or ""):
        valid = validate_email(match)
        if valid and valid not in seen:
            seen.add(valid)
            found.append(valid)
    return found


def validate_phone(raw_phone: str) -> str | None:
    cleaned = raw_phone.strip()
    if cleaned.lower().startswith("tel:"):
        cleaned = cleaned[4:].strip()

    has_plus = cleaned.startswith("+")
    digits = re.sub(r"\D", "", cleaned)
    if not (8 <= len(digits) <= 15):
        return None

    # Skip obvious date strings (e.g. 20261124) or repeated dummy digits
    if len(set(digits)) <= 2 or digits in ("1234567890", "0123456789"):
        return None
    if len(digits) == 8 and digits.startswith(("19", "20")):
        return None

    return f"tel:+{digits}" if has_plus else f"tel:{digits}"


def extract_valid_phones(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in PHONE_PATTERN.findall(text or ""):
        # Require either leading + or standard separator characters to reduce false positives on IDs
        if not ("+" in match or "-" in match or "(" in match or " " in match.strip()):
            continue
        valid = validate_phone(match)
        if valid and valid not in seen:
            seen.add(valid)
            found.append(valid)
    return found[:3]


def normalize_whatsapp_link(raw_url: str) -> str | None:
    parsed = urlparse(raw_url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.")

    if host == "wa.me":
        digits = re.sub(r"\D", "", parsed.path.strip("/"))
        if 8 <= len(digits) <= 15:
            return f"https://wa.me/{digits}"
        return None

    if host == "api.whatsapp.com" and parsed.path.startswith("/send"):
        qs = parse_qs(parsed.query)
        phone_vals = qs.get("phone") or []
        if phone_vals:
            digits = re.sub(r"\D", "", phone_vals[0])
            if 8 <= len(digits) <= 15:
                return f"https://wa.me/{digits}"
    return None


def extract_whatsapp_links(text: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in WHATSAPP_URL_PATTERN.findall(text or ""):
        norm = normalize_whatsapp_link(match)
        if norm and norm not in seen:
            seen.add(norm)
            links.append(norm)
    return links


def is_safe_public_url(url: str, resolve_dns: bool = True) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return False
    if is_search_engine_url(url):
        return False

    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False

    def _bad_ip(ip_str: str) -> bool:
        addr = ipaddress.ip_address(ip_str)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        )

    try:
        return not _bad_ip(host)
    except ValueError:
        pass

    if "." not in host:
        return False

    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return False
        for info in infos:
            if _bad_ip(info[4][0]):
                return False
    return True
