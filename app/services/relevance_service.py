import logging
import re

from app.schemas import ParsedQuery, RawCandidate
from app.services.llm_service import LLMClient
from app.utils.normalizers import is_likely_prospect_name

logger = logging.getLogger(__name__)


def compute_heuristic_score(candidate: RawCandidate, parsed: ParsedQuery) -> float:
    haystack = f"{candidate.name} {candidate.snippet} {candidate.profile_url}".lower()
    score = 0.2

    interest_tokens = [
        t for t in re.split(r"\W+", parsed.interest.lower()) if len(t) >= 3
    ]
    audience_tokens = [
        t for t in re.split(r"\W+", parsed.audience.lower()) if len(t) >= 3
    ]
    topic_tokens = set(interest_tokens + audience_tokens)
    if topic_tokens and any(tok in haystack for tok in topic_tokens):
        score += 0.35

    loc_parts = [
        p.lower()
        for p in (parsed.location.city, parsed.location.state, parsed.location.country)
        if p
    ]
    if loc_parts and any(lp in haystack for lp in loc_parts):
        score += 0.25

    if candidate.platform in {"LinkedIn", "Instagram", "X", "YouTube", "Threads", "Facebook"}:
        score += 0.1
    if candidate.extra_links:
        score += 0.1

    return min(score, 1.0)


async def filter_relevant_candidates(
    raw_query: str,
    parsed: ParsedQuery,
    candidates: list[RawCandidate],
    llm_client: LLMClient,
    max_candidates_for_llm: int = 25,
) -> list[RawCandidate]:
    if not candidates:
        return []

    for cand in candidates:
        cand.relevance_score = compute_heuristic_score(cand, parsed)

    candidates.sort(key=lambda c: c.relevance_score, reverse=True)
    shortlist = candidates[:max_candidates_for_llm]

    payload = [
        {
            "index": idx,
            "name": c.name,
            "platform": c.platform,
            "profile_url": c.profile_url,
            "snippet": c.snippet[:280],
        }
        for idx, c in enumerate(shortlist)
    ]

    try:
        decisions = await llm_client.evaluate_candidates(raw_query, parsed, payload)
    except Exception as exc:
        logger.warning("Falling back to deterministic relevance scoring: %s", exc)
        return [c for c in shortlist if c.relevance_score >= 0.45]

    decision_map = {
        int(d["index"]): d
        for d in decisions
        if isinstance(d, dict) and isinstance(d.get("index"), int)
    }

    verified: list[RawCandidate] = []
    for idx, cand in enumerate(shortlist):
        verdict = decision_map.get(idx)
        if verdict is None:
            if cand.relevance_score >= 0.55:
                verified.append(cand)
            continue

        if not verdict.get("relevant", False):
            continue

        llm_score = float(verdict.get("score", cand.relevance_score))
        if llm_score < 0.4:
            continue

        refined_name = str(verdict.get("name") or "").strip()
        if refined_name and is_likely_prospect_name(refined_name):
            cand.name = refined_name

        refined_loc = str(verdict.get("location") or "").strip()
        if refined_loc:
            cand.location = refined_loc

        cand.relevance_score = llm_score
        verified.append(cand)

    verified.sort(key=lambda c: c.relevance_score, reverse=True)
    return verified
