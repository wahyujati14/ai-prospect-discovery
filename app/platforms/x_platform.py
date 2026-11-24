from app.platforms.base import PlatformAdapter
from app.schemas import ParsedQuery


class XPlatform(PlatformAdapter):
    platform_name = "X"

    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        loc = parsed.location.city or parsed.location.country or ""
        return [
            f'(site:x.com OR site:twitter.com) -inurl:status "{parsed.interest}" "{loc}"'.strip(),
        ]
