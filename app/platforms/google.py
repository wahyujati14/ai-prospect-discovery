from app.platforms.base import PlatformAdapter
from app.schemas import ParsedQuery


class GooglePlatform(PlatformAdapter):
    platform_name = "Google"

    def build_queries(self, parsed: ParsedQuery) -> list[str]:
        loc = parsed.location.display_label()
        base = parsed.audience or parsed.interest
        if parsed.target_type == "business" or any(
            w in base.lower() for w in ("owner", "founder", "agency", "restaurant", "company")
        ):
            return [
                f'{base} {loc} "contact" OR "about" -top -best -yelp -clutch',
                f'"{parsed.interest}" {loc} founder OR owner email OR contact -directory',
            ]
        return [
            f'{base} {loc} club OR community OR enthusiast profile -news -wikipedia',
        ]
