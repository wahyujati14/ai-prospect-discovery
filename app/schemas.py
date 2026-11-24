from typing import Literal
from pydantic import BaseModel, Field, field_validator


ALLOWED_PLATFORMS = (
    "Google",
    "LinkedIn",
    "X",
    "YouTube",
    "Instagram",
    "WhatsApp",
    "Facebook",
    "Email",
    "Threads",
    "Phone",
)


class ProspectDiscoveryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        examples=["Football lovers in Washington DC in USA"],
    )

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("Search query must contain at least 3 characters.")
        return cleaned


class QueryLocation(BaseModel):
    city: str | None = None
    state: str | None = None
    country: str | None = None

    def display_label(self) -> str:
        parts: list[str] = []
        for item in (self.city, self.state, self.country):
            if not item:
                continue
            val = item.strip()
            if val and val.lower() not in [p.lower() for p in parts]:
                parts.append(val)
        if len(parts) == 3 and "dc" in parts[0].lower() and "columbia" in parts[1].lower():
            return f"{parts[0]}, {parts[2]}"
        return ", ".join(parts)


class ParsedQuery(BaseModel):
    interest: str
    audience: str
    location: QueryLocation = Field(default_factory=QueryLocation)
    target_type: Literal["individual", "business"] = "individual"
    keywords: list[str] = Field(default_factory=list)


class SocialLink(BaseModel):
    platform: str
    link: str


class RawCandidate(BaseModel):
    name: str
    platform: str
    profile_url: str
    handle: str = ""
    location: str = ""
    snippet: str = ""
    source_url: str = ""
    extra_links: list[SocialLink] = Field(default_factory=list)
    relevance_score: float = 0.0


class ProspectRecord(BaseModel):
    name: str
    location: str = ""
    social_link: list[SocialLink] = Field(default_factory=list)


class ProspectDiscoveryResponse(BaseModel):
    success: bool = True
    query: str
    total_prospects: int
    prospects: list[ProspectRecord] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: str | None = None
