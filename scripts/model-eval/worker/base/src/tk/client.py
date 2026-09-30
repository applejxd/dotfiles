"""Tiny API client with retries."""

from . import transport
from .config import Config


class Client:
    def __init__(self, config: Config):
        self.config = config

    def url(self, path: str) -> str:
        return self.config.base_url.rstrip("/") + "/" + path.lstrip("/")

    def post(self, path: str, payload: dict) -> dict:
        last: Exception | None = None
        for _ in range(self.config.retries + 1):
            try:
                return transport.send(self.url(path), payload)
            except ConnectionError as e:
                last = e
        assert last is not None
        raise last
