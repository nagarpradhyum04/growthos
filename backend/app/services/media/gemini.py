"""Google Gemini API media provider.

- Images: "Nano Banana" (gemini-2.5-flash-image) via models/{model}:generateContent with
  responseModalities=["IMAGE"]; the image comes back base64-encoded in candidates[].content.parts[].inlineData.
- Video: Veo via models/{model}:predictLongRunning, then the operation is polled until done and the
  generated video URI is downloaded with the API key.
Model ids are configurable (GEMINI_IMAGE_MODEL / GEMINI_VIDEO_MODEL).
"""
import base64
import logging
import time

import httpx

from app.config import Settings
from app.services.media import MediaError, MediaProvider, MediaResult

logger = logging.getLogger(__name__)
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiMediaProvider(MediaProvider):
    name = "gemini"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, poll_seconds: float = 10.0):
        if not settings.gemini_api_key:
            raise MediaError("GEMINI_API_KEY is not set")
        self.settings = settings
        self._client = httpx.Client(timeout=120, transport=transport, follow_redirects=True,
                                    headers={"x-goog-api-key": settings.gemini_api_key})
        self.poll_seconds = poll_seconds

    def _post(self, url: str, body: dict) -> dict:
        try:
            r = self._client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise MediaError(f"Gemini API unreachable: {type(exc).__name__}") from exc
        if r.status_code >= 400:
            raise MediaError(f"Gemini API error HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def generate_image(self, prompt: str, *, aspect_ratio: str, brand: dict) -> MediaResult:
        model = self.settings.gemini_image_model
        data = self._post(f"{BASE_URL}/models/{model}:generateContent", {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}},
        })
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return MediaResult(base64.b64decode(inline["data"]),
                                       inline.get("mimeType") or inline.get("mime_type") or "image/png", self.name, model)
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "no image in response"
        raise MediaError(f"Image generation returned no image ({reason})")

    def generate_video(self, prompt: str, *, aspect_ratio: str, brand: dict) -> MediaResult:
        model = self.settings.gemini_video_model
        op = self._post(f"{BASE_URL}/models/{model}:predictLongRunning", {
            "instances": [{"prompt": prompt}],
            "parameters": {"aspectRatio": aspect_ratio},
        })
        name = op.get("name")
        if not name:
            raise MediaError("Video generation did not return an operation")
        deadline = time.monotonic() + self.settings.video_timeout_seconds
        while not op.get("done"):
            if time.monotonic() > deadline:
                raise MediaError("Video generation timed out")
            time.sleep(self.poll_seconds)
            try:
                r = self._client.get(f"{BASE_URL}/{name}")
            except httpx.HTTPError as exc:
                raise MediaError(f"Gemini API unreachable while polling: {type(exc).__name__}") from exc
            if r.status_code >= 400:
                raise MediaError(f"Polling failed HTTP {r.status_code}")
            op = r.json()
        if op.get("error"):
            raise MediaError(f"Video generation failed: {op['error'].get('message', op['error'])}")
        resp = op.get("response", {})
        # Field names differ between API/SDK versions; accept both shapes.
        samples = (resp.get("generateVideoResponse", {}).get("generatedSamples")
                   or resp.get("generatedVideos") or resp.get("generated_videos") or [])
        uri = samples[0].get("video", {}).get("uri") if samples else None
        if not uri:
            raise MediaError("Video generation finished without a video (it may have been filtered)")
        try:
            v = self._client.get(uri)
        except httpx.HTTPError as exc:
            raise MediaError(f"Video download failed: {type(exc).__name__}") from exc
        if v.status_code >= 400:
            raise MediaError(f"Video download failed HTTP {v.status_code}")
        return MediaResult(v.content, v.headers.get("content-type", "video/mp4").split(";")[0], self.name, model)
