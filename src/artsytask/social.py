"""Social media discovery for a matched artist.

Two tiers: first-party links a platform exposes directly, then an
optional Tavily search fallback for the top-ranked match only. Enable the
fallback with `TAVILY_API_KEY`; without it, only first-party data is used.

We never guess a handle and probe it -- an unauthenticated
Instagram/Facebook page returns a login wall whether or not the account
exists, so "200 OK" proves nothing. Fallback candidates must mention the
artist's name and look like a profile URL, not a post permalink.
"""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from artsytask.models import ArtistProfile

_SOURCE_PRIORITY = ("Artfinder", "Fine Art America", "1stDibs")

_TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
_MAX_RESULTS = 8

# Domains that are never the "official website" result even if they show
# up in search: social platforms (handled separately) and the art
# marketplaces we already source from directly.
_NON_WEBSITE_DOMAINS = {
    "instagram.com", "facebook.com", "twitter.com", "x.com", "pinterest.com",
    "fineartamerica.com", "1stdibs.com", "artfinder.com", "phaidon.com",
    "wikipedia.org", "en.wikipedia.org", "youtube.com", "linkedin.com",
}


@dataclass
class SocialLinks:
    links: dict[str, str] = field(default_factory=dict)
    via_search: set[str] = field(default_factory=set)


def _pick(profiles: list[ArtistProfile], attr: str) -> str | None:
    by_platform = {p.platform: getattr(p, attr) for p in profiles if getattr(p, attr)}
    for platform in _SOURCE_PRIORITY:
        if platform in by_platform:
            return by_platform[platform]
    return next(iter(by_platform.values()), None)


def _domain(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _mentions_artist(result: dict, name_tokens: list[str]) -> bool:
    text = f"{result.get('title', '')} {result.get('content', '')}".lower()
    return all(tok.lower() in text for tok in name_tokens if len(tok) > 1)


# Instagram/Facebook path segments that mean "this is a post/group/reel,
# not the account's own profile page" -- a permalink to a photo someone
# else posted mentioning the artist is not "the artist's Instagram".
_NON_PROFILE_PATH_SEGMENTS = {
    "p", "reel", "reels", "stories", "explore", "accounts", "tv",
    "groups", "posts", "photo", "watch", "events", "share",
}


def _is_profile_url(url: str) -> bool:
    path_segments = [s for s in urlsplit(url).path.split("/") if s]
    if not path_segments:
        return False
    return path_segments[0].lower() not in _NON_PROFILE_PATH_SEGMENTS


def _tavily_search(query: str) -> list[dict]:
    api_key = os.environ.get(_TAVILY_API_KEY_ENV)
    if not api_key:
        return []
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = client.search(query, search_depth="basic", max_results=_MAX_RESULTS)
        return response.get("results", [])
    except Exception:
        # Any SDK/network/response-shape failure should degrade to "no
        # fallback data", never break the search.
        return []


def _search_fallback(artist_name: str, missing_fields: set[str]) -> dict[str, str]:
    """Fill only `missing_fields` (a subset of Instagram/Facebook/Website)."""
    if not missing_fields:
        return {}

    # Plain natural-language phrasing: Tavily is semantic, not
    # keyword/boolean, and quoted/"OR" syntax hurt relevance in testing.
    results = _tavily_search(f"{artist_name} artist official Instagram Facebook website")
    name_tokens = artist_name.split()
    found: dict[str, str] = {}

    for result in results:
        url = result.get("url", "")
        if not url or not _mentions_artist(result, name_tokens):
            continue
        domain = _domain(url)

        if "Instagram" in missing_fields and "Instagram" not in found and "instagram.com" in domain:
            if _is_profile_url(url):
                found["Instagram"] = url
        elif "Facebook" in missing_fields and "Facebook" not in found and "facebook.com" in domain:
            if _is_profile_url(url):
                found["Facebook"] = url
        elif "Website" in missing_fields and "Website" not in found and domain not in _NON_WEBSITE_DOMAINS:
            found["Website"] = url

    return found


def discover_social_links(profiles: list[ArtistProfile], allow_search_fallback: bool = False) -> SocialLinks:
    """Instagram/Facebook/Website for one artist identity.

    `profiles` must all be the *same* real person -- never a whole
    "uncertain" group, since pooling across possibly-different people
    misattributes their links. `allow_search_fallback` should only be True
    for the single highest-ranked identity.
    """
    links: dict[str, str] = {}
    instagram = _pick(profiles, "instagram_url")
    facebook = _pick(profiles, "facebook_url")
    website = _pick(profiles, "website_url")

    if instagram:
        links["Instagram"] = instagram
    if facebook:
        links["Facebook"] = facebook
    if website:
        links["Website"] = website

    via_search: set[str] = set()
    if allow_search_fallback:
        missing = {"Instagram", "Facebook", "Website"} - links.keys()
        name = profiles[0].name
        found = _search_fallback(name, missing)
        links.update(found)
        via_search = set(found.keys())

    return SocialLinks(links=links, via_search=via_search)
