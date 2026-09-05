# Artist Discovery & Profile Matching

A prototype that searches for an artist by name across several art platforms,
merges results that look like the same real person, ranks the most likely
match first, and surfaces social media links when a source exposes them.
Built for the ArtyTraders AI/ML Engineer test task.

## Running it

```bash
uv sync
uv run streamlit run src/artsytask/app.py
```

Open the URL Streamlit prints (defaults to `http://localhost:8501`), enter a
first and last name (e.g. `Pablo` / `Picasso`), and click Search.

The first search touching Fine Art America or Artfinder takes ~25-30 seconds
once, to cache their artist sitemaps under `.cache/`. Every search after that
is fast.

### Optional: social media search fallback

```bash
export TAVILY_API_KEY=your-key   # free, no credit card, from tavily.com
```

Without it, social links come from first-party platform data only (see
[Social media discovery](#social-media-discovery)).

## Architecture

```
sources/            one module per platform, each implementing
  base.py           Source.search(first_name, last_name) -> list[ArtistProfile]
  fineartamerica.py
  onestdibs.py
  artfinder.py
  phaidon.py
models.py           ArtistProfile, MatchGroup
matching.py         clusters ArtistProfiles into "same real artist" groups
ranking.py          scores groups against the query, most likely first
social.py           picks Instagram/Facebook/website for a matched identity
social_analysis.py  optional follower/post-count summary for Instagram
search.py           ties sources + matching + ranking together
app.py              Streamlit UI
```

`search.py` calls every source, catching exceptions per-source so one
platform failing doesn't take down the whole search. Results are clustered
(`matching.py`), then ranked and truncated to the top 5 (`ranking.py`).

## Platforms

| Platform | Status | Approach |
|---|---|---|
| **Fine Art America** | Working | No usable name search exists, but FAA publishes a public artist sitemap (~288k URLs). Cached locally, fuzzy-matched against the query. Profile pages are static HTML with bio/image and first-party social links. |
| **Artfinder** | Working | Search page is a client-rendered SPA, but Artfinder also publishes an artist sitemap; individual profile pages are server-rendered with a full JSON payload (bio, avatar, country, social links). |
| **1stDibs** | Partial | Search is robots-disallowed, but creator pages at predictable `/creators/firstname-lastname/` slugs are static and allowed, so we guess the slug. Only genuine biography pages are accepted — 1stDibs also serves a generic "\<name\> at 1stDibs" SEO page for almost any plausible name. |
| **Artspace** | Merged into Phaidon | `artspace.com` now redirects entirely to a Phaidon landing page, but Artspace's print catalog is still sold inside Phaidon's Shopify store. Uses Phaidon's documented read-only search API, filtered to actual art pieces (not the books Phaidon also publishes) via the product `vendor` field. |

## Matching

`matching.py` scores every pair of profiles 0-100 on four signals: name,
location, birth/death year, and biography similarity. Names compare
surname and given name separately, each gated on a shared first letter to
avoid anagram-style false matches like "Lisa"/"Isla". Missing fields are
excluded rather than penalized, except a missing bio next to a substantial
one, which counts as weak negative evidence.

Biography similarity uses local sentence embeddings (`fastembed`, no API
key, no torch), rescaled against an empirically observed different-person
baseline rather than used as raw cosine similarity — general-purpose
embeddings pick up on shared art-bio phrasing almost as much as genuine
identity. Embeddings and the word-overlap approach they replaced were both
checked against real same-person and different-person profile pairs;
embeddings won by a significant margin on genuine paraphrase matches.

The same name comparison is reused for ranking, so both stages share one
notion of what counts as a good name match.

Profiles are clustered with **complete-linkage** (a profile must match every
existing cluster member, not just the closest one) to avoid dissimilar
profiles chaining together transitively through a shared middle profile.

Each group gets one of three confidence labels:
- **confirmed** — either cross-platform agreement above a high threshold, or
  a single-source result whose name is an exact match to the query.
- **uncertain** — merged, but on borderline evidence.
- **single_source** — no corroboration and not an exact query match.

The UI renders `confirmed`/`single_source` groups as one summary card, but
splits an `uncertain` group into per-profile sections (same name vs.
different name) rather than picking one profile to represent the whole
group — otherwise a genuinely different person sharing a name could be
silently hidden or have their data blended with someone else's. Social
media lookups follow the same per-identity principle, computed separately
for each distinguished profile rather than pooled across a whole group.

## Ranking

Groups are sorted primarily by name match to the query (75% weight), with
completeness and cross-platform confirmation as tie-breakers (25%). When the
leading results are multiple different real people who each independently
earned an exact-match `confirmed` label, they share one numbered card
instead of being ranked against each other, since neither is a stronger
match than the other.

## Social media discovery

`social.py` surfaces Instagram/Facebook/website links only when a platform
exposes them first-party (Artfinder's own data, or links FAA embeds on an
artist's page). 1stDibs and Phaidon never have this signal.

Deliberately not implemented: guessing a handle and checking if it resolves
— unauthenticated Instagram/Facebook pages return a generic login wall
regardless of whether the account exists, so a `200 OK` proves nothing.

For the top-ranked identity only, missing fields fall back to a real search
([Tavily](https://tavily.com), opt-in via `TAVILY_API_KEY`). Every result is
required to actually mention the artist's name before being trusted, and a
candidate must look like a profile URL, not a post/reel permalink. Google
Custom Search and Gemini API grounding were tried first and dropped —
Custom Search stopped accepting new sign-ups in 2026, and Gemini grounding
requires a funded (not just linked) Google Cloud billing account.

## Social media analysis (optional)

Instagram still exposes aggregate follower/following/post counts to a
logged-out request via the profile page's `og:description` meta tag;
`social_analysis.py` parses this. Facebook redirects unauthenticated
requests to a login wall, so it isn't analyzed. Posting recency,
most-discussed topics, and active/inactive status all need the actual post
timeline, which isn't part of what either platform's public page exposes —
rather than approximate these, they're left out.

## Known limitations

- **Concatenated slugs don't fuzzy-match.** FAA/Artfinder usernames that
  aren't hyphenated (`aaronblaise`) won't be found via the sitemap-slug
  search key, even with a real, populated profile.
- **1stDibs returns at most one profile per search.** No sitemap exists to
  fuzzy match against, so the slug guess either hits or misses. 1stDibs
  redirects some name variants itself (`henri-toulouse-lautrec` resolves to
  Henri *de* Toulouse-Lautrec), but a name whose slug differs beyond that
  is missed, and a second creator sharing a name could never be returned
  alongside the first.
- **Self-reported location can coincide across different people**, since
  it's a "current country" field, not birthplace — a residual source of
  false "uncertain" merges between different people.
- **Phaidon only covers artists with a current Artspace print edition** —
  historical figures who are only in Phaidon's book catalog return nothing.
- **Rule-based name/location/year scoring, plus embeddings for bio only**
  — no LLM calls, no image comparison. Nicknames, transliteration, and
  name-order swaps can still confuse the name scorer. The bio embedding
  rescaling is calibrated against a handful of real pairs, not a proper
  validation set.
- **Single-query, synchronous**, with a fixed per-request delay — not built
  for concurrent or bulk use.
- **Sitemap caches never expire** — a new artist joining after the cache
  was built won't be found until it's deleted and rebuilt.
- **Social-presence analysis only covers Instagram follower/post counts** —
  no posting recency, topics, activity status, or Facebook data.

## What a production version would add

- Better disambiguation between an artist's own website and their
  representing gallery, which the search fallback currently conflates.
- A properly validated embedding calibration (more than a handful of
  pairs), or an LLM-as-judge pass for cases the scorer still misses
  (nicknames, transliteration, name-order swaps).
- Async/parallel source fetching (currently sequential).
- A proper cache with TTL/invalidation instead of a build-once file.
- Tests — this was built and validated interactively against real requests,
  not with a test suite, given the ~1 day scope.
