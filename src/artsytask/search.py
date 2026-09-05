"""Ties the four sources together into one artist search."""

import logging

from artsytask.matching import cluster_profiles, confirm_exact_query_matches
from artsytask.models import MatchGroup
from artsytask.ranking import rank_groups
from artsytask.sources.artfinder import ArtfinderSource
from artsytask.sources.base import Source
from artsytask.sources.fineartamerica import FineArtAmericaSource
from artsytask.sources.onestdibs import OneStDibsSource
from artsytask.sources.phaidon import PhaidonSource

logger = logging.getLogger(__name__)

MAX_RESULTS = 5

SOURCES: list[Source] = [
    FineArtAmericaSource(),
    OneStDibsSource(),
    ArtfinderSource(),
    PhaidonSource(),
]


def search_artist(first_name: str, last_name: str) -> list[MatchGroup]:
    profiles = []
    for source in SOURCES:
        try:
            profiles.extend(source.search(first_name, last_name))
        except Exception:
            # One platform failing (layout change, timeout, block) shouldn't
            # take the whole search down -- surface partial results instead.
            logger.exception("Source %s failed for %r %r", source.name, first_name, last_name)

    groups = cluster_profiles(profiles)
    confirm_exact_query_matches(groups, first_name, last_name)
    ranked = rank_groups(groups, first_name, last_name)
    return ranked[:MAX_RESULTS]


if __name__ == "__main__":
    import sys

    first, last = (sys.argv[1:3] if len(sys.argv) >= 3 else ("Pablo", "Picasso"))
    results = search_artist(first, last)

    if not results:
        print(f"No matches found for {first} {last}.")
    for i, group in enumerate(results, 1):
        lead = group.profiles[0]
        print(f"\n#{i} [{group.confidence}, score={group.rank_score:.1f}] {lead.name}")
        for p in group.profiles:
            print(f"    - {p.platform}: {p.profile_url}")
