from app.platforms.base import PlatformAdapter
from app.schemas import ParsedQuery


class FacebookPlatform(PlatformAdapter):
    platform_name = "Facebook"

    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        loc = parsed.location.city or parsed.location.country or ""
        return [
            f'site:facebook.com -inurl:groups -inurl:events -inurl:posts "{parsed.interest}" "{loc}"'.strip(),
        ]
