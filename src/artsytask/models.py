from typing import Literal

from pydantic import BaseModel


class ArtistProfile(BaseModel):
    """A single artist result as scraped from one platform."""

    name: str
    platform: str
    profile_url: str
    image_url: str | None = None
    bio: str | None = None
    birth_date: str | None = None
    death_date: str | None = None
    location: str | None = None

    # Populated directly when a source exposes them; otherwise left for the
    # social-discovery step to fill in for the top-ranked match.
    instagram_url: str | None = None
    facebook_url: str | None = None
    website_url: str | None = None


MatchConfidence = Literal["confirmed", "uncertain", "single_source"]


class MatchGroup(BaseModel):
    """One or more ArtistProfiles believed to refer to the same real artist."""

    profiles: list[ArtistProfile]
    confidence: MatchConfidence
    rank_score: float = 0.0
