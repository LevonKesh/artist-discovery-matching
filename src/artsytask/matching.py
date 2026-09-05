"""Cross-platform artist matching / dedup.

Groups ArtistProfiles likely referring to the same real artist, using a
weighted combination of name, location, birth/death year, and biography
similarity. Missing fields are excluded from a pair's score rather than
penalized, since most profiles are missing something. The exception is
biography: a substantial bio next to a missing one is weak negative
evidence -- suspicious, but not proof of a mismatch.

Biography similarity uses local sentence embeddings (fastembed) rather
than word overlap, to catch paraphrases that share no vocabulary.
"""

import itertools
import re

from rapidfuzz import fuzz

from artsytask.models import ArtistProfile, MatchConfidence, MatchGroup

CONFIRMED_THRESHOLD = 80.0
UNCERTAIN_THRESHOLD = 60.0

_WORD_RE = re.compile(r"[a-z]{4,}")
_STOPWORDS = {
    "with", "that", "this", "from", "have", "were", "been", "their",
    "which", "these", "those", "about", "into", "over", "such", "also",
    "more", "most", "some", "each", "when", "where", "while", "after",
    "before", "through", "artist", "artwork", "artworks", "painting",
    "paintings", "print", "prints", "canvas", "shop", "purchase", "framed",
    "poster", "posters", "greeting", "cards", "business", "days", "ready",
    "ship", "products", "print-on-demand", "world", "life", "work", "works",
    "many", "well", "just", "like", "than", "very", "born", "used", "based",
}


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split()
    if len(parts) < 2:
        return name.strip(), ""
    return parts[0], parts[-1]


def name_similarity(a: str, b: str) -> float:
    """How closely two artist names match, 0-100.

    Surname is weighted higher than given name (many unrelated artists
    share a first name, far fewer a surname). Comparing the whole string
    at once scores "Andre Alexander" vs "Alexander Andrew" deceptively
    high, since neither component matches the same role.
    """
    a_first, a_last = _split_name(a)
    b_first, b_last = _split_name(b)
    if not a_last or not b_last:
        return fuzz.token_sort_ratio(a, b)
    return 0.65 * _name_part_score(a_last, b_last) + 0.35 * _name_part_score(a_first, b_first)


def _name_score(a: ArtistProfile, b: ArtistProfile) -> float:
    return name_similarity(a.name, b.name)


def _name_part_score(a: str, b: str) -> float:
    """Similarity for one name component (given name or surname)."""
    a, b = a.lower(), b.lower()
    ratio = fuzz.ratio(a, b)
    # Character-overlap similarity can't tell a real near-miss
    # ("Jon"/"John") from two unrelated names that happen to share
    # letters ("Lisa"/"Isla" are anagrams, scoring 75/100). Real
    # nicknames and misspellings overwhelmingly preserve the first
    # letter; coincidental overlap doesn't.
    if a and b and a[0] != b[0]:
        ratio = min(ratio, 30.0)
    return ratio


def _location_score(a: ArtistProfile, b: ArtistProfile) -> float | None:
    if not a.location or not b.location:
        return None
    loc_a, loc_b = a.location.lower().strip(), b.location.lower().strip()
    if loc_a == loc_b:
        return 100.0
    if loc_a in loc_b or loc_b in loc_a:
        return 80.0
    return 8.0


def _years_score(a: ArtistProfile, b: ArtistProfile) -> float | None:
    if not a.birth_date or not b.birth_date:
        return None
    if a.birth_date != b.birth_date:
        return 5.0  # conflicting birth years: very strong "different artist" signal
    if a.death_date and b.death_date:
        return 100.0 if a.death_date == b.death_date else 10.0
    return 85.0


_MIN_BIO_WORDS = 3
_MISSING_BIO_SCORE = 25.0  # one side has a real bio, the other has none at all

# Raw cosine similarity between different people's bios still lands
# ~0.5-0.73 (shared art-bio register, not identity), while a real match
# scored 0.89. Floor/ceiling rescale past that range so unrelated bios
# land near 0. Calibrated on a handful of real pairs, not a validation
# set -- worth rechecking if this scorer looks wrong on new cases.
_COSINE_FLOOR = 0.75
_COSINE_CEILING = 0.90

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding

        _embedding_model = TextEmbedding()
    return _embedding_model


def _bio_words(bio: str | None) -> set[str]:
    if not bio:
        return set()
    return {w for w in _WORD_RE.findall(bio.lower()) if w not in _STOPWORDS}


def _has_bio(profile: ArtistProfile) -> bool:
    return len(_bio_words(profile.bio)) >= _MIN_BIO_WORDS


def build_bio_embeddings(profiles: list[ArtistProfile]) -> dict[int, object]:
    """One embedding per profile with a substantial bio, keyed by
    id(profile). Batched once per search rather than per pair."""
    candidates = [p for p in profiles if _has_bio(p)]
    if not candidates:
        return {}
    model = _get_embedding_model()
    vectors = list(model.embed([p.bio for p in candidates]))
    return {id(p): v for p, v in zip(candidates, vectors)}


def _cosine_to_score(cosine: float) -> float:
    span = _COSINE_CEILING - _COSINE_FLOOR
    normalized = (cosine - _COSINE_FLOOR) / span
    return max(0.0, min(1.0, normalized)) * 100.0


def _bio_score(
    a: ArtistProfile,
    b: ArtistProfile,
    embeddings: dict[int, object] | None = None,
) -> float | None:
    has_a, has_b = _has_bio(a), _has_bio(b)

    if not has_a and not has_b:
        return None  # neither side has enough bio text to compare at all
    if has_a != has_b:
        return _MISSING_BIO_SCORE

    if embeddings is not None and id(a) in embeddings and id(b) in embeddings:
        vec_a, vec_b = embeddings[id(a)], embeddings[id(b)]
    else:
        # No precomputed embeddings (e.g. pair_score called directly,
        # outside cluster_profiles) -- embed just this one pair.
        model = _get_embedding_model()
        vec_a, vec_b = list(model.embed([a.bio, b.bio]))

    cosine = float(sum(x * y for x, y in zip(vec_a, vec_b)))  # vectors are unit-normalized
    return _cosine_to_score(cosine)


def pair_score(
    a: ArtistProfile,
    b: ArtistProfile,
    embeddings: dict[int, object] | None = None,
) -> float:
    """Score how likely two profiles are the same real artist, 0-100."""
    signals: list[tuple[float, float]] = [(3.0, _name_score(a, b))]
    for weight, score in (
        (2.5, _location_score(a, b)),
        (2.5, _years_score(a, b)),
        (1.0, _bio_score(a, b, embeddings)),
    ):
        if score is not None:
            signals.append((weight, score))

    total_weight = sum(w for w, _ in signals)
    return sum(w * s for w, s in signals) / total_weight


def cluster_profiles(profiles: list[ArtistProfile]) -> list[MatchGroup]:
    embeddings = build_bio_embeddings(profiles)

    def score(a: ArtistProfile, b: ArtistProfile) -> float:
        return pair_score(a, b, embeddings)

    clusters: list[list[ArtistProfile]] = []

    for profile in profiles:
        # Complete-linkage: a profile must match *every* existing member,
        # not just the closest one, or dissimilar profiles can chain
        # together transitively through a shared middle profile.
        best_cluster: list[ArtistProfile] | None = None
        best_score = -1.0
        for cluster in clusters:
            cluster_score = min(score(profile, member) for member in cluster)
            if cluster_score > best_score:
                best_score, best_cluster = cluster_score, cluster

        if best_cluster is not None and best_score >= UNCERTAIN_THRESHOLD:
            best_cluster.append(profile)
        else:
            clusters.append([profile])

    groups = []
    for cluster in clusters:
        confidence: MatchConfidence
        if len(cluster) == 1:
            confidence = "single_source"
        else:
            min_score = min(score(a, b) for a, b in itertools.combinations(cluster, 2))
            confidence = "confirmed" if min_score >= CONFIRMED_THRESHOLD else "uncertain"
        groups.append(MatchGroup(profiles=cluster, confidence=confidence))
    return groups


def confirm_exact_query_matches(groups: list[MatchGroup], first_name: str, last_name: str) -> None:
    """Upgrade a single_source group to "confirmed" when its name exactly
    matches the query -- no corroboration doesn't mean uncertain identity;
    an exact name match is confidence via a different route than
    cross-platform agreement. Mutates `groups` in place. Exact string
    match only (case/whitespace normalized), no fuzzy threshold.
    """
    query = f"{first_name} {last_name}".strip().lower()
    for group in groups:
        if group.confidence == "single_source" and group.profiles[0].name.strip().lower() == query:
            group.confidence = "confirmed"
