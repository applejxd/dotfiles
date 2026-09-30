"""Human-readable durations."""

_UNITS = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))


def format_duration(seconds: int) -> str:
    """Format seconds as e.g. ``1h30m``. Zero is ``0s``."""
    if seconds < 0:
        raise ValueError("negative duration")
    if seconds == 0:
        return "0s"
    parts = []
    for name, size in _UNITS:
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n}{name}")
    return "".join(parts)
