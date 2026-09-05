"""Artfinder source.

Artfinder's search page is a client-rendered SPA and /api/* is
robots-disallowed, but it publishes an artist sitemap (~5k URLs) and
/artist/<slug>/ pages embed a full Next.js data payload in a
__NEXT_DATA__ script tag. So the sitemap acts as a directory (same
approach as fineartamerica.py) and profile data is read from that JSON
rather than scraped from HTML -- including the artist's own
Instagram/Facebook/website links when they've filled them in.
"""

import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process

from artsytask.models import ArtistProfile

PLATFORM = "Artfinder"
SITEMAP_URL = "https://assets.artfinder.com/sitemaps/en/sitemap-artists-1.xml"
CACHE_PATH = Path(__file__).resolve().parents[3] / ".cache" / "artfinder_artists.tsv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArtsyTaskBot/0.1; +artist discovery prototype)"}
REQUEST_DELAY_SECONDS = 0.3
MATCH_SCORE_THRESHOLD = 75
MAX_CANDIDATES = 5

_LOC_RE = re.compile(r"<loc>(.*?)</loc>")
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _slug_to_name(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip()


def _build_index() -> list[tuple[str, str]]:
    resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    entries = []
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


def _social_url(username: str | None, base: str) -> str | None:
    return f"{base}{username}" if username else None


def _scrape_profile(url: str) -> ArtistProfile | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    match = _NEXT_DATA_RE.search(resp.text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        artist = data["props"]["pageProps"]["artist"]
    except (json.JSONDecodeError, KeyError):
        return None

    bio_html = (
        data.get("props", {})
        .get("pageProps", {})
        .get("initArtistPageInfo", {})
        .get("about", {})
        .get("biography", {})
        .get("text")
    )
    bio = BeautifulSoup(bio_html, "lxml").get_text(" ", strip=True) if bio_html else artist.get("intro")

    return ArtistProfile(
        name=artist.get("name") or "",
        platform=PLATFORM,
        profile_url=artist.get("url") or url,
        image_url=artist.get("avatar_url"),
        bio=bio,
        location=artist.get("country"),
        instagram_url=_social_url(artist.get("instagram_username"), "https://instagram.com/"),
        facebook_url=artist.get("facebook_url"),
        website_url=artist.get("website_url"),
    )


class ArtfinderSource:
    name = PLATFORM

    def search(self, first_name: str, last_name: str) -> list[ArtistProfile]:
        query = f"{first_name} {last_name}".strip()
        index = _load_index()
        # Same short-candidate blowup risk as fineartamerica.py -- guard
        # with a real scorer and a minimally name-shaped candidate.
        filtered_index = [(name, url) for name, url in index if len(name) >= 5 and " " in name]
        names = [name for name, _ in filtered_index]

        matches = process.extract(
            query, names, scorer=fuzz.token_sort_ratio, limit=MAX_CANDIDATES, score_cutoff=MATCH_SCORE_THRESHOLD
        )

        results: list[ArtistProfile] = []
        for _matched_name, _score, idx in matches:
            _, url = filtered_index[idx]
            profile = _scrape_profile(url)
            if profile and profile.name:
                results.append(profile)
            time.sleep(REQUEST_DELAY_SECONDS)
        return results


if __name__ == "__main__":
    import sys

    first, last = (sys.argv[1:3] if len(sys.argv) >= 3 else ("Pablo", "Picasso"))
    for artist in ArtfinderSource().search(first, last):
        print(artist.model_dump_json(indent=2))
