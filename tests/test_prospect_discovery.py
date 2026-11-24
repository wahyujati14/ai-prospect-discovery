from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import app, get_prospect_service
from app.schemas import ParsedQuery, QueryLocation, RawCandidate, SocialLink
from app.services.deduplication_service import build_prospect_records, consolidate_candidates
from app.services.profile_extractor import extract_links_and_contacts_from_html
from app.services.prospect_service import ProspectDiscoveryService
from app.services.query_service import heuristic_parse_query
from app.utils.normalizers import canonicalize_profile_url, clean_prospect_name, is_likely_prospect_name
from app.utils.validators import (
    extract_valid_emails,
    extract_whatsapp_links,
    is_search_engine_url,
    validate_phone,
)


@pytest.mark.parametrize(
    ("query", "expected_interest", "expected_city", "expected_country"),
    [
        ("Football lovers in Washington DC in USA", "Football", "Washington DC", "USA"),
        ("Digital marketing agency owners in New York USA", "Digital marketing agency", "New York", "USA"),
        ("Startup founders in London UK", "Startup", "London", "UK"),
        ("Cricket lovers in Ahmedabad India", "Cricket", "Ahmedabad", "India"),
        ("Restaurant owners in Dubai UAE", "Restaurant", "Dubai", "UAE"),
    ],
)
def test_five_mandatory_queries_parse_location_and_interest(
    query: str,
    expected_interest: str,
    expected_city: str,
    expected_country: str,
) -> None:
    parsed = heuristic_parse_query(query)
    assert expected_interest.lower() in parsed.interest.lower()
    assert parsed.location.city == expected_city
    assert parsed.location.country == expected_country


def test_canonicalize_profile_url_accepts_profiles_and_rejects_search_or_posts() -> None:
    assert canonicalize_profile_url("https://www.google.com/search?q=football") is None
    assert canonicalize_profile_url("https://www.instagram.com/p/C9abc123/") is None
    assert canonicalize_profile_url("https://www.linkedin.com/jobs/view/12345") is None

    li = canonicalize_profile_url("https://uk.linkedin.com/in/alex-founder?trk=public")
    assert li == ("LinkedIn", "https://www.linkedin.com/in/alex-founder", "alex-founder")

    tw = canonicalize_profile_url("https://twitter.com/dcfootyclub")
    assert tw == ("X", "https://x.com/dcfootyclub", "dcfootyclub")

    th = canonicalize_profile_url("https://www.threads.net/@dcfootyclub/post/xyz")
    assert th == ("Threads", "https://www.threads.net/@dcfootyclub", "dcfootyclub")

    wa = canonicalize_profile_url("https://api.whatsapp.com/send?phone=971501234567&text=Hi")
    assert wa == ("WhatsApp", "https://wa.me/971501234567", "971501234567")


def test_listicle_titles_are_rejected_as_prospect_names() -> None:
    assert not is_likely_prospect_name("Top 10 Digital Marketing Agencies in New York")
    assert not is_likely_prospect_name("15 Best Restaurants in Dubai")
    assert is_likely_prospect_name(clean_prospect_name("Marcus Vance - Founder | LinkedIn"))


def test_contact_validators_filter_junk_and_normalize_formats() -> None:
    text = "Reach us at hello@metrofooty.org, noreply@example.com, banner@2x.png, https://wa.me/12025550198"
    assert extract_valid_emails(text) == ["mailto:hello@metrofooty.org"]
    assert extract_whatsapp_links(text) == ["https://wa.me/12025550198"]
    assert validate_phone("+1 (202) 555-0198") == "tel:+12025550198"
    assert validate_phone("20261124") is None


def test_html_contact_and_social_extraction() -> None:
    html = """
    <html><body>
      <a href="mailto:founder@hudsonagency.io">Email</a>
      <a href="https://www.linkedin.com/in/sarah-jenkins-nyc">LinkedIn</a>
      <a href="https://www.instagram.com/hudsonagency/">Instagram</a>
      <a href="https://api.whatsapp.com/send?phone=12125550144">Chat on WhatsApp</a>
    </body></html>
    """
    links = extract_links_and_contacts_from_html(html, "https://hudsonagency.io")
    platforms = {item.platform: item.link for item in links}
    assert platforms["Email"] == "mailto:founder@hudsonagency.io"
    assert platforms["LinkedIn"] == "https://www.linkedin.com/in/sarah-jenkins-nyc"
    assert platforms["Instagram"] == "https://www.instagram.com/hudsonagency/"
    assert platforms["WhatsApp"] == "https://wa.me/12125550144"


def test_deduplication_consolidates_same_person_and_separates_different_cities() -> None:
    candidates = [
        RawCandidate(
            name="Daniel Carter",
            platform="LinkedIn",
            profile_url="https://www.linkedin.com/in/danielcarterdc",
            handle="danielcarterdc",
            location="Washington DC, USA",
            snippet="Washington DC football supporter & community organizer",
        ),
        RawCandidate(
            name="Daniel Carter",
            platform="Instagram",
            profile_url="https://www.instagram.com/danielcarterdc/",
            handle="danielcarterdc",
            location="Washington DC, USA",
            snippet="DC football weekends",
            extra_links=[SocialLink(platform="Email", link="mailto:dan@dcfooty.org")],
        ),
        RawCandidate(
            name="Daniel Carter",
            platform="LinkedIn",
            profile_url="https://www.linkedin.com/in/daniel-carter-sydney",
            handle="daniel-carter-sydney",
            location="Sydney, Australia",
            snippet="Accountant in Sydney",
        ),
    ]

    merged = consolidate_candidates(candidates)
    records = build_prospect_records(merged)
    assert len(records) == 2

    dc_record = next(r for r in records if "Washington" in r.location)
    platforms = [s.platform for s in dc_record.social_link]
    assert "LinkedIn" in platforms
    assert "Instagram" in platforms
    assert "Email" in platforms


def test_prospect_discovery_endpoint_end_to_end() -> None:
    mock_llm = AsyncMock()
    mock_llm.parse_search_query.return_value = ParsedQuery(
        interest="Football",
        audience="Football lovers",
        location=QueryLocation(
            city="Washington DC",
            state="District of Columbia",
            country="USA",
        ),
        target_type="individual",
        keywords=["football", "supporters"],
    )
    mock_llm.evaluate_candidates.return_value = [
        {
            "index": 0,
            "relevant": True,
            "score": 0.92,
            "name": "District Ultras DC",
            "location": "Washington DC, USA",
        }
    ]

    mock_search = AsyncMock()

    async def _fake_search(q: str, max_results: int = 6) -> list[dict[str, str]]:
        if "linkedin.com" in q:
            return [
                {
                    "title": "District Ultras DC | LinkedIn",
                    "link": "https://www.linkedin.com/company/district-ultras-dc",
                    "snippet": "Football supporters group in Washington DC. Contact: info@districtultras.org",
                }
            ]
        if "instagram.com" in q:
            return [
                {
                    "title": "District Ultras DC (@districtultrasdc) • Instagram",
                    "link": "https://www.instagram.com/districtultrasdc/",
                    "snippet": "Washington DC football lovers community",
                }
            ]
        return []

    mock_search.search.side_effect = _fake_search

    settings = Settings(gemini_api_key="test-key", cache_ttl_seconds=300, max_website_enrichments=0)
    service = ProspectDiscoveryService(
        settings=settings,
        llm_client=mock_llm,
        search_service=mock_search,
    )
    app.dependency_overrides[get_prospect_service] = lambda: service

    try:
        with patch("app.services.prospect_service.enrich_website_candidates", new=AsyncMock()):
            client = TestClient(app)
            resp = client.post(
                "/prospect-discovery",
                json={"query": "Football lovers in Washington DC in USA"},
            )
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["success"] is True
            assert payload["query"] == "Football lovers in Washington DC in USA"
            assert payload["total_prospects"] == 1
            prospect = payload["prospects"][0]
            assert prospect["name"] == "District Ultras DC"
            assert prospect["location"] == "Washington DC, USA"
            returned_platforms = {s["platform"] for s in prospect["social_link"]}
            assert returned_platforms == {"LinkedIn", "Instagram", "Email"}
            for s in prospect["social_link"]:
                assert not is_search_engine_url(s["link"])
    finally:
        app.dependency_overrides.clear()
