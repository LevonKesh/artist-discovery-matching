"""Phaidon (formerly Artspace) source.

artspace.com now redirects entirely to phaidon.com; the standalone
marketplace is gone, but Artspace survives as a print imprint inside
Phaidon's Shopify storefront. Phaidon's agents.md permits read-only use of
their predictive-search JSON endpoint, so we use that instead of scraping.

The storefront mixes Phaidon's books with Artspace art pieces; the product
`vendor` field tells them apart, and results are filtered to art pieces
only. Cost: historical figures like Picasso, who only have books here,
return nothing from this source.
"""

import re
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from artsytask.models import ArtistProfile

PLATFORM = "Phaidon (Artspace)"
BASE_URL = "https://www.phaidon.com"
SEARCH_URL = f"{BASE_URL}/en-us/search/suggest.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArtsyTaskBot/0.1; +artist discovery prototype)"}
MATCH_SCORE_THRESHOLD = 90
MAX_CANDIDATES = 5
ART_VENDOR = "Artspace"

_YEAR_RANGE_RE = re.compile(r"\((\d{4})\s*[-–]\s*(\d{4})\)")
_NATIONALITY_RE = re.compile(r"\b([A-Z][a-z]+)\s+artist\b")


def _clean_html(html: str) -> str | None:
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return text or None


def _clean_url(raw_url: str) -> str:
    parts = urlsplit(raw_url)
    path = parts.path if parts.path.startswith("/") else f"/{parts.path}"
    return urlunsplit((("https", "www.phaidon.com", path, "", "")))


class PhaidonSource:
    name = PLATFORM

    def search(self, first_name: str, last_name: str) -> list[ArtistProfile]:
        query = f"{first_name} {last_name}".strip()
        try:
            resp = requests.get(
                SEARCH_URL,
                params={"q": query, "resources[type]": "product", "resources[limit]": MAX_CANDIDATES},
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            products = resp.json()["resources"]["results"].get("products", [])
        except (requests.RequestException, ValueError, KeyError):
            return []

        results: list[ArtistProfile] = []
        for product in products:
            if product.get("vendor") != ART_VENDOR:
                continue

            title = product.get("title") or ""
            bio = _clean_html(product.get("body") or "")
            # An art piece's title is the artwork's name ("Day at Night"),
            # not the artist's, so title similarity alone can't tell
            # relevance -- fall back to checking the artist's name in the
            # product description, which Artspace pieces reliably include.
            name_tokens = [t for t in query.split() if len(t) > 1]
            mentioned_in_bio = bool(bio) and all(t.lower() in bio.lower() for t in name_tokens)
            if fuzz.token_set_ratio(query, title) < MATCH_SCORE_THRESHOLD and not mentioned_in_bio:
                continue
            birth_date = death_date = None
            if bio:
                year_match = _YEAR_RANGE_RE.search(bio)
                if year_match:
                    birth_date, death_date = year_match.group(1), year_match.group(2)
            location = _NATIONALITY_RE.search(bio).group(1) if bio and _NATIONALITY_RE.search(bio) else None

            url = product.get("url")
            if not url:
                continue

            results.append(
                ArtistProfile(
                    name=query,
                    platform=PLATFORM,
                    profile_url=_clean_url(url),
                    image_url=product.get("image"),
                    bio=bio,
                    birth_date=birth_date,
                    death_date=death_date,
                    location=location,
                )
            )
        return results


if __name__ == "__main__":
    import sys

    first, last = (sys.argv[1:3] if len(sys.argv) >= 3 else ("Pablo", "Picasso"))
    for artist in PhaidonSource().search(first, last):
        print(artist.model_dump_json(indent=2))
