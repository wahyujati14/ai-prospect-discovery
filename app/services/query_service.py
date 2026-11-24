from collections import OrderedDict
import re

from app.schemas import ParsedQuery, QueryLocation
from app.services.llm_service import LLMClient

BUSINESS_HINTS = ("owner", "owners", "founder", "founders", "agency", "agencies", "company", "ceo")


def heuristic_parse_query(raw_query: str) -> ParsedQuery:
    """Deterministic parser used only if upstream LLM fails mid-flight after key check."""
    cleaned = " ".join(raw_query.strip().split())
    parts = re.split(r"\s+in\s+", cleaned, flags=re.I)

    audience = parts[0].strip() if parts else cleaned
    loc_tokens = [p.strip(" ,") for p in parts[1:] if p.strip(" ,")]

    city: str | None = None
    state: str | None = None
    country: str | None = None

    if len(loc_tokens) >= 2:
        city = loc_tokens[0]
        country = loc_tokens[-1]
        if len(loc_tokens) > 2:
            state = loc_tokens[1]
    elif len(loc_tokens) == 1:
        sub = [s.strip() for s in loc_tokens[0].split(",") if s.strip()]
        if len(sub) >= 2:
            city, country = sub[0], sub[-1]
        else:
            words = loc_tokens[0].split()
            if len(words) >= 2 and words[-1].upper() in {"USA", "UK", "UAE", "INDIA", "CANADA"}:
                city = " ".join(words[:-1])
                country = words[-1]
            else:
                city = loc_tokens[0]

    if city and city.lower() in ("washington dc", "washington d.c."):
        state = state or "District of Columbia"

    interest = re.sub(
        r"\b(lovers?|enthusiasts?|fans?|owners?|founders?|players?|creators?)\b",
        "",
        audience,
        flags=re.I,
    )
    interest = " ".join(interest.split()).strip() or audience

    is_business = any(tok in audience.lower() for tok in BUSINESS_HINTS)
    return ParsedQuery(
        interest=interest,
        audience=audience,
        location=QueryLocation(city=city, state=state, country=country),
        target_type="business" if is_business else "individual",
        keywords=[w for w in [interest, audience] if w],
    )


class QueryService:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client
        self._cache: OrderedDict[str, ParsedQuery] = OrderedDict()

    async def understand_query(self, raw_query: str) -> ParsedQuery:
        key = raw_query.strip().lower()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        parsed = await self.llm.parse_search_query(raw_query)
        self._cache[key] = parsed
        while len(self._cache) > 256:
            self._cache.popitem(last=False)
        return parsed
