import streamlit as st

from artsytask.models import ArtistProfile, MatchGroup
from artsytask.search import search_artist
from artsytask.social import discover_social_links
from artsytask.social_analysis import analyze_instagram

st.set_page_config(page_title="Artist Discovery", page_icon=":material/palette:", layout="centered")


def _confidence_label(group: MatchGroup) -> str:
    if group.confidence == "confirmed":
        # "confirmed" covers two different reasons: multiple platforms
        # corroborating each other, or a single source whose name is an
        # exact match to the query (see confirm_exact_query_matches).
        # "across platforms" would be a false claim for the second case.
        if len(group.profiles) > 1:
            return ":material/check_circle: Confirmed match across platforms"
        return ":material/check_circle: Confirmed match"
    if group.confidence == "uncertain":
        return ":material/help: Uncertain match"
    return ":material/info: Found on one platform"


def _best(group: MatchGroup, field: str) -> str | None:
    """Longest non-empty value for `field` across the group's profiles."""
    values = [getattr(p, field) for p in group.profiles if getattr(p, field)]
    return max(values, key=len) if values else None


def _render_profile_details(p: ArtistProfile, bio_char_limit: int = 400) -> None:
    """One profile's own image/bio/details -- never blended with another profile's."""
    col_img, col_info = st.columns([1, 3])
    with col_img:
        if p.image_url:
            st.image(p.image_url, width="stretch")
        else:
            st.markdown("*No image*")
    with col_info:
        st.markdown(f"**{p.name}** — [{p.platform}]({p.profile_url})")

        details = []
        if p.birth_date or p.death_date:
            details.append(f"**Born/Died:** {p.birth_date or '?'} – {p.death_date or 'present'}")
        if p.location:
            details.append(f"**Location:** {p.location}")
        if details:
            st.markdown(" &nbsp;|&nbsp; ".join(details))

        if p.bio:
            st.write(p.bio[:bio_char_limit] + ("…" if len(p.bio) > bio_char_limit else ""))
            if len(p.bio) > bio_char_limit:
                with st.expander("Full biography"):
                    st.write(p.bio)


def _render_social(profiles: list[ArtistProfile], allow_search_fallback: bool, show_empty_message: bool) -> None:
    """Social links + Instagram stats for one identity (never a whole
    possibly-multi-person group -- see discover_social_links' docstring)."""
    social = discover_social_links(profiles, allow_search_fallback=allow_search_fallback)
    if social.links:
        st.markdown("**Social media:**")

        def _label(key: str) -> str:
            return f"{key} (via web search)" if key in social.via_search else key

        st.markdown(
            " &nbsp;|&nbsp; ".join(f"[{_label(k)}]({v})" for k, v in social.links.items())
        )
        if social.links.get("Instagram"):
            stats = analyze_instagram(social.links["Instagram"])
            if stats:
                st.caption(
                    f":material/bar_chart: Instagram: {stats['followers']:,} followers, "
                    f"{stats['posts']:,} posts"
                )
    elif show_empty_message:
        st.caption(
            "No social profiles found for this top match. "
            "See the README for how to enable web-search-based discovery."
        )


def render_result(rank: int, group: MatchGroup) -> None:
    name = group.profiles[0].name

    with st.container(border=True):
        st.subheader(f"{rank}. {name}")
        st.caption(_confidence_label(group))

        if group.confidence == "uncertain":
            # Not confident every profile here is the same person, so
            # never pick one "best" image/bio for the whole group -- show
            # each in full. Split same-name (a real, if uncorroborated,
            # signal) from different-name (merged on weaker secondary
            # evidence only) so it's never ambiguous which is which.
            same_name = [p for p in group.profiles if p.name.strip().lower() == name.strip().lower()]
            different_name = [p for p in group.profiles if p.name.strip().lower() != name.strip().lower()]

            if same_name:
                st.caption(
                    f"Same name across {len(same_name)} source(s), but not "
                    "otherwise corroborated -- shown separately below."
                    if len(same_name) > 1
                    else "Found under this exact name on one source."
                )
                for i, p in enumerate(same_name):
                    if i > 0:
                        st.divider()
                    _render_profile_details(p)
                    # Not confirmed to be one person, so social links are
                    # looked up per profile, never pooled. Search fallback
                    # only for the first (best-ranked) profile, to avoid
                    # spending API quota on every same-named candidate.
                    _render_social(
                        [p],
                        allow_search_fallback=(rank == 1 and i == 0),
                        show_empty_message=(rank == 1 and i == 0),
                    )

            if different_name:
                if same_name:
                    st.divider()
                st.caption(
                    f":material/warning: Different name found ({len(different_name)}) -- included only "
                    "because other evidence didn't rule it out, not because the name matches:"
                )
                for i, p in enumerate(different_name):
                    if i > 0:
                        st.divider()
                    _render_profile_details(p)
                    # Each is its own identity -- own social lookup, no
                    # pooling, no search fallback (secondary/low-confidence).
                    _render_social([p], allow_search_fallback=False, show_empty_message=False)
        else:
            _render_confirmed_body(group, allow_search_fallback=(rank == 1))


def _render_confirmed_body(group: MatchGroup, allow_search_fallback: bool) -> None:
    """Body for a confirmed/single_source group: every profile in it is
    confidently the same person, so pooling image/bio/social across them
    is correct (unlike the uncertain branch, which never pools)."""
    image_url = _best(group, "image_url")
    bio = _best(group, "bio")
    birth = _best(group, "birth_date")
    death = _best(group, "death_date")
    location = _best(group, "location")

    col_img, col_info = st.columns([1, 3])
    with col_img:
        if image_url:
            st.image(image_url, width="stretch")
        else:
            st.markdown("*No image*")
    with col_info:
        details = []
        if birth or death:
            details.append(f"**Born/Died:** {birth or '?'} – {death or 'present'}")
        if location:
            details.append(f"**Location:** {location}")
        if details:
            st.markdown(" &nbsp;|&nbsp; ".join(details))
        if bio:
            st.write(bio[:500] + ("…" if len(bio) > 500 else ""))

    # A platform can contribute more than one profile to a
    # (confirmed/single-source) group -- show one link per
    # platform, preferring whichever has the richer bio.
    by_platform: dict[str, ArtistProfile] = {}
    for p in group.profiles:
        existing = by_platform.get(p.platform)
        if existing is None or len(p.bio or "") > len(existing.bio or ""):
            by_platform[p.platform] = p

    st.markdown("**Found on:**")
    for p in by_platform.values():
        st.markdown(f"- [{p.platform}]({p.profile_url})")

    if bio and len(bio) > 500:
        with st.expander("Full biography"):
            st.write(bio)

    _render_social(group.profiles, allow_search_fallback=allow_search_fallback, show_empty_message=allow_search_fallback)


def render_tied_confirmed_matches(rank: int, groups: list[MatchGroup]) -> None:
    """Different real people who each exactly match the query, tied for
    the same rank (e.g. two different "Amy Hamilton"s) -- share one card
    instead of separate numbers, since neither outranks the other."""
    name = groups[0].profiles[0].name

    with st.container(border=True):
        st.subheader(f"{rank}. {name}")
        st.caption(
            f":material/info: {len(groups)} different artists share this exact name -- "
            "shown together since none outranks the others."
        )
        for i, group in enumerate(groups):
            if i > 0:
                st.divider()
            st.caption(_confidence_label(group))
            _render_confirmed_body(group, allow_search_fallback=(rank == 1 and i == 0))


def main() -> None:
    st.title(":material/palette: Artist Discovery & Profile Matching")
    st.write(
        "Search for an artist across Fine Art America, 1stDibs, Artfinder, and Phaidon "
        "(Artspace's catalog now lives inside Phaidon's store -- see the README for why)."
    )

    with st.form("search_form"):
        col1, col2 = st.columns(2)
        first_name = col1.text_input("Artist First Name", placeholder="Pablo")
        last_name = col2.text_input("Artist Last Name", placeholder="Picasso")
        submitted = st.form_submit_button("Search", type="primary")

    if not submitted:
        return

    if not first_name.strip() or not last_name.strip():
        st.warning("Please enter both a first and last name.")
        return

    with st.spinner("Searching Fine Art America, 1stDibs, Artfinder, and Phaidon…"):
        results = search_artist(first_name.strip(), last_name.strip())

    if not results:
        st.info(f"No matches found for **{first_name} {last_name}** on the covered platforms.")
        return

    st.success(f"Found {len(results)} possible match(es), most likely first.")

    # If the top result(s) are exact-name confirmed matches tied on rank
    # score, they share one card instead of separate numbers -- see
    # render_tied_confirmed_matches for why.
    lead_name = results[0].profiles[0].name.strip().lower()
    tie_count = 0
    for group in results:
        if group.confidence == "confirmed" and group.profiles[0].name.strip().lower() == lead_name:
            tie_count += 1
        else:
            break

    if tie_count > 1:
        render_tied_confirmed_matches(1, results[:tie_count])
        remaining = results[tie_count:]
        start = 2
    else:
        remaining = results
        start = 1

    for i, group in enumerate(remaining, start):
        render_result(i, group)


main()
