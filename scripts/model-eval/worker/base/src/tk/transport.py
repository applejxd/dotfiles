"""Network transport. Tests replace ``send``."""


def send(url: str, payload: dict, *, timeout: float | None = None) -> dict:
    """Send ``payload`` to ``url`` and return the decoded response.

    ``timeout`` is in seconds; ``None`` waits forever.
    """
    raise RuntimeError("network access is disabled in this build")
