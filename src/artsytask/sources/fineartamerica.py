"""Fine Art America source.

FAA's search pages are product-oriented and expose no artist-name search,
so the public artist sitemap (~288k URLs across 6 files) acts as a
directory: cached locally once, then fuzzy-matched against the query.
Profile pages are static HTML with usable meta tags.
"""

import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process

from artsytask.models import ArtistProfile

PLATFORM = "Fine Art America"
BASE_URL = "https://fineartamerica.com"
SITEMAP_URLS = [
    f"{BASE_URL}/sitemap-artists-{i}.xml" for i in range(1, 7)
]
CACHE_PATH = Path(__file__).resolve().parents[3] / ".cache" / "fineartamerica_artists.tsv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArtsyTaskBot/0.1; +artist discovery prototype)"}
REQUEST_DELAY_SECONDS = 0.3
MATCH_SCORE_THRESHOLD = 75
MAX_CANDIDATES = 5

_LOC_RE = re.compile(r"<loc>(.*?)</loc>")
_SLUG_PREFIX_RE = re.compile(r"^\d+-")


def _slug_to_name(slug: str) -> str:
    return _SLUG_PREFIX_RE.sub("", slug).replace("-", " ").strip()


def _build_index() -> list[tuple[str, str]]:
    """Download all artist sitemaps and return (display_name, url) pairs."""
    entries: list[tuple[str, str]] = []
    for sitemap_url in SITEMAP_URLS:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        for loc in _LOC_RE.findall(resp.text):
            slug = loc.rstrip("/").rsplit("/", 1)[-1]
            entries.append((_slug_to_name(slug), loc))
    return entries


def _load_index() -> list[tuple[str, str]]:
    if CACHE_PATH.exists():
        lines = CACHE_PATH.read_text(encoding="utf-8").splitlines()
        return [tuple(line.split("\t", 1)) for line in lines if "\t" in line]

    entries = _build_index()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        "\n".join(f"{name}\t{url}" for name, url in entries), encoding="utf-8"
    )
    return entries


_BOILERPLATE_RE = re.compile(
    r"^Shop for artwork by .+?\.\s*Purchase canvas prints, framed prints, tapestries, posters, "
    r"greeting cards, and more\.\s*.+?ready to ship in 3\s*-\s*4 business days\.\s*",
    re.IGNORECASE,
)

_LOCATION_PATTERNS = [
    re.compile(r"based in ([^.]+)", re.IGNORECASE),
    re.compile(r"living in ([^.]+)", re.IGNORECASE),
    re.compile(r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+){0,2})-based artist"),
]


def _strip_boilerplate(description: str | None) -> str | None:
    if not description:
        return None
    cleaned = _BOILERPLATE_RE.sub("", description).strip()
    return cleaned or None


def _extract_location(description: str | None) -> str | None:
    if not description:
        return None
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(description)
        if match:
            return match.group(1).strip()
    return None


_WEBSITE_LINK_RE = re.compile(r"Visit .*Website", re.IGNORECASE)


def _extract_social(soup: BeautifulSoup) -> tuple[str | None, str | None, str | None]:
    """First-party social links FAA embeds on an artist's profile page.

    Every profile also links FAA's own house accounts, filtered out here so
    the platform's account isn't misreported as the artist's.
    """
    instagram = facebook = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "instagram.com/" in href and "fineartamerica" not in href.lower() and not instagram:
            instagram = href
        elif "facebook.com/" in href and "fineartamerica" not in href.lower() and not facebook:
            facebook = href

    website_link = soup.find("a", string=_WEBSITE_LINK_RE)
    website = website_link.get("href") if website_link else None

    return instagram, facebook, website


def _scrape_profile(url: str, display_name: str) -> ArtistProfile | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    def meta(name: str | None = None, prop: str | None = None) -> str | None:
        tag = soup.find("meta", attrs={"name": name} if name else {"property": prop})
        return tag.get("content") if tag else None

    title = meta(prop="og:title") or display_name
    name = re.sub(r"\s+Art for Sale$", "", title).strip()
    description = meta(name="description") or meta(prop="og:description")
    instagram_url, facebook_url, website_url = _extract_social(soup)

    return ArtistProfile(
        name=name,
        platform=PLATFORM,
        profile_url=url,
        image_url=meta(prop="og:image"),
        bio=_strip_boilerplate(description),
        location=_extract_location(description),
        instagram_url=instagram_url,
        facebook_url=facebook_url,
        website_url=website_url,
    )


class FineArtAmericaSource:
    name = PLATFORM

    def search(self, first_name: str, last_name: str) -> list[ArtistProfile]:
        query = f"{first_name} {last_name}".strip()
        index = _load_index()
        # WRatio inflates scores for very short candidates (FAA has many
        # placeholder accounts with slugs like "a-a"); token_sort_ratio
        # doesn't, and requiring a name-shaped candidate filters the rest.
        filtered_index = [(name, url) for name, url in index if len(name) >= 5 and " " in name]
        names = [name for name, _ in filtered_index]

        matches = process.extract(
            query, names, scorer=fuzz.token_sort_ratio, limit=MAX_CANDIDATES, score_cutoff=MATCH_SCORE_THRESHOLD
        )

        results: list[ArtistProfile] = []
        for matched_name, _score, idx in matches:
            _, url = filtered_index[idx]
            profile = _scrape_profile(url, matched_name)
            if profile:
                results.append(profile)
            time.sleep(REQUEST_DELAY_SECONDS)
        return results


if __name__ == "__main__":
    import sys

    first, last = (sys.argv[1:3] if len(sys.argv) >= 3 else ("Pablo", "Picasso"))
    for artist in FineArtAmericaSource().search(first, last):
        print(artist.model_dump_json(indent=2))
