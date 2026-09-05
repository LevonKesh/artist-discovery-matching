"""Ranks match groups against the query so the most likely match is first.

Driven primarily by how closely the group's name matches the query, with
completeness and confidence as secondary tie-breakers. Name comparison is
shared with matching.py so both use the same notion of a good name match.
"""

from artsytask.matching import name_similarity
from artsytask.models import MatchGroup

_COMPLETENESS_FIELDS = ("image_url", "bio", "birth_date", "death_date", "location")
_CONFIDENCE_BONUS = {"confirmed": 10.0, "uncertain": 0.0, "single_source": 0.0}

NAME_WEIGHT = 0.75
COMPLETENESS_WEIGHT = 0.25


def _completeness(group: MatchGroup) -> float:
    filled = {
        field
        for field in _COMPLETENESS_FIELDS
        if any(getattr(p, field) for p in group.profiles)
    }
    return len(filled) / len(_COMPLETENESS_FIELDS) * 100.0


def rank_groups(groups: list[MatchGroup], first_name: str, last_name: str) -> list[MatchGroup]:
    query = f"{first_name} {last_name}".strip()

    for group in groups:
        name_score = max(name_similarity(query, p.name) for p in group.profiles)
        group.rank_score = (
            NAME_WEIGHT * name_score
            + COMPLETENESS_WEIGHT * _completeness(group)
            + _CONFIDENCE_BONUS[group.confidence]
        )

    return sorted(groups, key=lambda g: g.rank_score, reverse=True)
