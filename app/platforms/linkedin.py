from app.platforms.base import PlatformAdapter
from app.schemas import ParsedQuery


class LinkedInPlatform(PlatformAdapter):
    platform_name = "LinkedIn"

    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        loc = parsed.location.city or parsed.location.country or ""
        role = parsed.audience or parsed.interest
        return [
            f'site:linkedin.com/in "{role}" "{loc}"'.strip(),
            f'site:linkedin.com/in {parsed.interest} "{loc}"'.strip(),
        ]
