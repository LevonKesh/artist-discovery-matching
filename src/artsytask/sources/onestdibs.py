"""1stDibs source.

Search is robots-disallowed on 1stDibs, but creator pages at
/creators/<slug>/ are static, allowed, and slugs are predictably
"firstname-lastname" -- so we guess the slug and fetch it directly.

That only ever finds the single canonical listing for a name: no
disambiguating two people who share one, and no alternate spellings.
"""

import re

import requests
from bs4 import BeautifulSoup

from artsytask.models import ArtistProfile

PLATFORM = "1stDibs"
BASE_URL = "https://www.1stdibs.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArtsyTaskBot/0.1; +artist discovery prototype)"}

# 1stDibs titles curated biography pages "<name> - <role> Biography and
# Price History on 1stDibs", where role varies by creator type ("Artist"
# for Picasso, "Designer" for van Gogh, Le Corbusier, Eames). Matching any
# role still excludes the generic "<name> at 1stDibs" SEO page, which
# 1stDibs generates for almost any plausible name.
_TITLE_SUFFIX_RE = re.compile(r"\s*-\s*\w+ Biography and Price History on 1stDibs$", re.IGNORECASE)
_YEAR_RE = re.compile(r"\d{4}")


def _slugify(first_name: str, last_name: str) -> str:
    raw = f"{first_name} {last_name}".strip().lower()
    raw = re.sub(r"[^a-z0-9\s-]", "", raw)
    return re.sub(r"\s+", "-", raw).strip("-")


def _parse_title_info(text: str) -> tuple[str | None, str | None, str | None]:
    """Parse a "Spanish, 1881-1973" style string into (location, birth, death)."""
    if "," not in text:
        return None, None, None
    location, years_part = text.split(",", 1)
    years = _YEAR_RE.findall(years_part)
    birth = years[0] if years else None
    death = years[1] if len(years) > 1 else None
    return location.strip(), birth, death


class OneStDibsSource:
    name = PLATFORM

    def search(self, first_name: str, last_name: str) -> list[ArtistProfile]:
        slug = _slugify(first_name, last_name)
        if not slug:
            return []

        url = f"{BASE_URL}/creators/{slug}/"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException:
            return []

        if not resp.ok:
            return []
        # A nonexistent slug redirects to the generic /creators/ directory
        # page rather than 404ing.
        if resp.url.rstrip("/") == f"{BASE_URL}/creators":
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        title_tag = soup.find("meta", attrs={"name": "og:title"})
        title = title_tag["content"] if title_tag else ""
        # 1stDibs generates a generic "Shop authentic pieces by X at
        # 1stDibs" page for essentially any plausible name -- that's
        # programmatic SEO, not evidence the artist has a real presence
        # here. Only the genuine curated-biography template (this title
        # suffix) counts as a match.
        if not _TITLE_SUFFIX_RE.search(title):
            return []
        name = _TITLE_SUFFIX_RE.sub("", title).strip()
        if not name:
            return []

        description_tag = soup.find("meta", attrs={"name": "description"})
        bio_div = soup.find(attrs={"data-tn": "facet-creator-description"})
        bio = bio_div.get_text(" ", strip=True) if bio_div else (
            description_tag["content"] if description_tag else None
        )

        title_div = soup.find(attrs={"data-tn": "facet-creator-title"})
        location, birth_date, death_date = (
            _parse_title_info(title_div.get_text(strip=True)) if title_div else (None, None, None)
        )

        return [
            ArtistProfile(
                name=name,
                platform=PLATFORM,
                profile_url=resp.url,
                image_url=None,  # 1stDibs shows artwork photos, not artist portraits
                bio=bio,
                birth_date=birth_date,
                death_date=death_date,
                location=location,
            )
        ]


if __name__ == "__main__":
    import sys

    first, last = (sys.argv[1:3] if len(sys.argv) >= 3 else ("Pablo", "Picasso"))
    for artist in OneStDibsSource().search(first, last):
        print(artist.model_dump_json(indent=2))
