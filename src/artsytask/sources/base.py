from typing import Protocol

from artsytask.models import ArtistProfile


class Source(Protocol):
    """Common interface every platform scraper implements."""

    name: str

    def search(self, first_name: str, last_name: str) -> list[ArtistProfile]:
        """Return candidate artist profiles matching the given name.

        Implementations should skip individual candidates that fail to
        fetch or parse rather than raising, so one bad result doesn't take
        down the whole search.
        """
        ...
