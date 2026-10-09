"""Media generation providers for social posts (images + short videos)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings


@dataclass
class MediaResult:
    data: bytes
    mime: str
    provider: str
    model: str


class MediaError(Exception):
    pass


class MediaProvider(ABC):
    name: str

    @abstractmethod
    def generate_image(self, prompt: str, *, aspect_ratio: str, brand: dict) -> MediaResult: ...

    @abstractmethod
    def generate_video(self, prompt: str, *, aspect_ratio: str, brand: dict) -> MediaResult: ...


def build_media_provider(settings: Settings) -> MediaProvider:
    if settings.media_provider == "gemini":
        from app.services.media.gemini import GeminiMediaProvider

        return GeminiMediaProvider(settings)
    if settings.media_provider in ("mock", ""):
        from app.services.media.mock import MockMediaProvider

        return MockMediaProvider()
    raise MediaError(f"Unknown MEDIA_PROVIDER '{settings.media_provider}'")
