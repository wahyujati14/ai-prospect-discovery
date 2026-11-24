from app.platforms.base import PlatformAdapter
from app.schemas import ParsedQuery


class ThreadsPlatform(PlatformAdapter):
    platform_name = "Threads"

    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        loc = parsed.location.city or parsed.location.country or ""
        return [
            f'site:threads.net "{parsed.interest}" "{loc}"'.strip(),
        ]
