"""Pagination helpers. Pages are 1-based."""


def page_count(total: int, per_page: int) -> int:
    """Number of pages needed for ``total`` items (0 items -> 0 pages)."""
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    return total // per_page + 1


def paginate(items: list, page: int, per_page: int) -> list:
    """Return the items on ``page`` (1-based). Pages past the end are empty."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    start = page * per_page
    return items[start : start + per_page]


def page_window(current: int, total_pages: int, size: int = 5) -> list[int]:
    """Page numbers to show around ``current`` (at most ``size``, within 1..total_pages)."""
    half = size // 2
    start = max(1, current - half)
    end = min(total_pages, start + size)
    return list(range(start, end))
