from app.platforms.base import PlatformAdapter
from app.schemas import ParsedQuery


class InstagramPlatform(PlatformAdapter):
    platform_name = "Instagram"

    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        loc = parsed.location.city or parsed.location.country or ""
        return [
            f'site:instagram.com -inurl:/p/ -inurl:/reel/ "{parsed.interest}" "{loc}"'.strip(),
        ]
