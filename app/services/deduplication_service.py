from app.schemas import ALLOWED_PLATFORMS, ProspectRecord, RawCandidate, SocialLink
from app.utils.normalizers import normalize_name_key
from app.utils.validators import is_search_engine_url

PLATFORM_ORDER = {name: idx for idx, name in enumerate(ALLOWED_PLATFORMS)}


def _locations_compatible(loc_a: str, loc_b: str) -> bool:
    a = loc_a.strip().lower()
    b = loc_b.strip().lower()
    if not a or not b or a == b:
        return True
    tokens_a = {t.strip() for t in a.replace(",", " ").split() if len(t.strip()) > 2}
    tokens_b = {t.strip() for t in b.replace(",", " ").split() if len(t.strip()) > 2}
    return bool(tokens_a & tokens_b)


def _candidate_all_links(candidate: RawCandidate) -> list[SocialLink]:
    links = [SocialLink(platform=candidate.platform, link=candidate.profile_url)]
    links.extend(candidate.extra_links)
    deduped: list[SocialLink] = []
    seen: set[str] = set()
    for item in links:
        if item.platform not in PLATFORM_ORDER:
            continue
        if is_search_engine_url(item.link):
            continue
        key = item.link.strip().rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _same_entity(existing: RawCandidate, incoming: RawCandidate) -> bool:
    existing_urls = {
        s.link.strip().rstrip("/").lower() for s in _candidate_all_links(existing)
    }
    incoming_urls = {
        s.link.strip().rstrip("/").lower() for s in _candidate_all_links(incoming)
    }
    # Shared profile link, email, or WhatsApp contact is a strong deterministic identity match
    if existing_urls & incoming_urls:
        return True

    if not _locations_compatible(existing.location, incoming.location):
        return False

    # Shared distinct social handle across platforms (e.g. @alexriveradc on X and Instagram)
    if (
        existing.handle
        and incoming.handle
        and len(existing.handle) >= 5
        and "." not in existing.handle
        and existing.handle.lower() == incoming.handle.lower()
    ):
        return True

    # Normalized full-name match (require multi-word name to avoid merging generic single words)
    key_a = normalize_name_key(existing.name)
    key_b = normalize_name_key(incoming.name)
    if key_a and key_a == key_b and len(key_a.split()) >= 2:
        return True

    return False


def consolidate_candidates(candidates: list[RawCandidate]) -> list[RawCandidate]:
    merged: list[RawCandidate] = []

    for cand in candidates:
        matched_target: RawCandidate | None = None
        for target in merged:
            if _same_entity(target, cand):
                matched_target = target
                break

        if matched_target is None:
            merged.append(cand.model_copy(deep=True))
            continue

        for link in _candidate_all_links(cand):
            existing_keys = {
                s.link.strip().rstrip("/").lower() for s in _candidate_all_links(matched_target)
            }
            if link.link.strip().rstrip("/").lower() not in existing_keys:
                matched_target.extra_links.append(link)

        if not matched_target.location and cand.location:
            matched_target.location = cand.location
        if len(cand.snippet) > len(matched_target.snippet):
            matched_target.snippet = f"{matched_target.snippet} | {cand.snippet}"[:600]
        matched_target.relevance_score = max(matched_target.relevance_score, cand.relevance_score)

    return merged


def build_prospect_records(candidates: list[RawCandidate]) -> list[ProspectRecord]:
    records: list[ProspectRecord] = []
    for cand in candidates:
        links = _candidate_all_links(cand)
        if not links or not cand.name.strip():
            continue
        links.sort(key=lambda s: PLATFORM_ORDER.get(s.platform, 99))
        records.append(
            ProspectRecord(
                name=cand.name.strip(),
                location=cand.location.strip(),
                social_link=links,
            )
        )
    return records
