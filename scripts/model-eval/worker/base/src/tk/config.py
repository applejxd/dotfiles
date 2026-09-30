"""Client configuration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    base_url: str
    retries: int = 3


def load_config(data: dict) -> Config:
    if "base_url" not in data:
        raise ValueError("base_url is required")
    retries = data.get("retries", 3)
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        raise ValueError("retries must be a non-negative int")
    return Config(base_url=data["base_url"], retries=retries)
