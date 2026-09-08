from pathlib import Path
from uuid import UUID

from backend.collectors.sponsor_logos import (
    BrandHit,
    SponsorLogosCollector,
    parse_brand_json,
)
from backend.models import Organization, OrgType, Sponsor
from pytest import MonkeyPatch

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ORG_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_parse_sponsor_logos_fixture_returns_records(monkeypatch: MonkeyPatch) -> None:
    html = (FIXTURES / "sponsor_page.html").read_text()
    monkeypatch.setattr(
        SponsorLogosCollector,
        "_qualify_image",
        lambda self, item: (item, b"fake-png", "image/png"),
    )
    monkeypatch.setattr(
        "backend.collectors.sponsor_logos.identify_brands",
        lambda logos, _payloads: [
            BrandHit(
                brand="Nike",
                confidence=0.91,
                detected_on_url=logos[0].detected_on_url,
                logo_image_url=logos[0].image_url,
                organization_id=logos[0].organization_id,
            ),
            BrandHit(
                brand="Lee Hardware",
                confidence=0.84,
                detected_on_url=logos[1].detected_on_url,
                logo_image_url=logos[1].image_url,
                organization_id=logos[1].organization_id,
            ),
        ],
    )
    monkeypatch.setattr(
        "backend.collectors.sponsor_logos.search_places_for_brand",
        lambda _collector, brand: [
            {
                "id": f"ChIJ{brand.replace(' ', '')}",
                "displayName": {"text": brand},
                "formattedAddress": "1 Market St, Richmond, VA 23219, USA",
                "websiteUri": "https://nike.example.com/" if brand == "Nike" else None,
                "nationalPhoneNumber": None,
                "rating": 4.5,
                "userRatingCount": 12,
            },
            {
                "id": f"ChIJ{brand.replace(' ', '')}2",
                "displayName": {"text": brand},
            },
        ],
    )
    collector = SponsorLogosCollector()
    try:
        parsed = collector.parse(
            {
                "pages": [
                    {
                        "organization_id": str(ORG_ID),
                        "url": "https://riverside-aau.example.com/",
                        "html": html,
                    }
                ]
            }
        )
        assert len(parsed) > 0
        assert len(parsed) == 2
        urls = {item.image_url for item in parsed}
        assert "https://cdn.example.com/brands/nike.png" in urls
        assert "https://cdn.example.com/hero.png" not in urls
        assert "https://cdn.example.com/icon.png" not in urls
        records = collector.to_records(parsed)
        sponsors = [record for record in records if isinstance(record, Sponsor)]
        businesses = [record for record in records if isinstance(record, Organization)]
        assert len(sponsors) == 2
        assert {sponsor.brand_name for sponsor in sponsors} == {"Nike", "Lee Hardware"}
        assert all(sponsor.extraction_confidence is not None for sponsor in sponsors)
        assert len(businesses) == 2
        assert all(org.org_type == OrgType.business for org in businesses)
        assert all(org.location_count == 2 for org in businesses)
    finally:
        collector.close()


def test_parse_brand_json_nulls_are_discarded() -> None:
    parsed = parse_brand_json(
        '[{"brand": "Nike", "confidence": 0.9}, {"brand": null, "confidence": null}, null]'
    )
    assert parsed[0][0] == "Nike"
    assert parsed[1][0] is None
    assert parsed[2][0] is None

