"""Optional, very basic social-presence summary for the top-ranked artist.

Instagram exposes aggregate follower/following/post counts in its
`og:description` meta tag to logged-out requests, so that's what's parsed
here. Facebook redirects those requests to a login wall, so it isn't
analyzed. Posting recency, topics, and activity status need the post
timeline, which neither platform exposes publicly -- left out rather than
guessed at.
"""

import re

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
REQUEST_TIMEOUT = 10

_STATS_RE = re.compile(
    r"([\d,.]+[KMB]?)\s*Followers,\s*([\d,.]+[KMB]?)\s*Following,\s*([\d,.]+[KMB]?)\s*Posts",
    re.IGNORECASE,
)
_MULTIPLIERS = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _parse_count(raw: str) -> int | None:
    raw = raw.strip().upper()
    suffix = raw[-1] if raw and raw[-1] in _MULTIPLIERS else None
    number_part = raw[:-1] if suffix else raw
    try:
        value = float(number_part.replace(",", ""))
    except ValueError:
        return None
    return int(value * _MULTIPLIERS[suffix]) if suffix else int(value)


def analyze_instagram(profile_url: str) -> dict[str, int] | None:
    """Follower/following/post counts from Instagram's public profile page.

    Returns None if the page doesn't expose the stats (wrong/removed
    handle, private account, or the page shape changed) -- never guesses.
    """
    try:
        resp = requests.get(profile_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    match = _STATS_RE.search(resp.text)
    if not match:
        return None

    followers, following, posts = (_parse_count(g) for g in match.groups())
    if followers is None:
        return None
    return {"followers": followers, "following": following, "posts": posts}
