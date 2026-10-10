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
from app.services.gemini_client import VERTEX, GeminiClient, GeminiHTTPError
from app.services.media import MediaError, MediaProvider, MediaResult

logger = logging.getLogger(__name__)


class GeminiMediaProvider(MediaProvider):
    name = "gemini"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, poll_seconds: float = 10.0):
        if not settings.gemini_api_key:
            raise MediaError("GEMINI_API_KEY is not set")
        self.settings = settings
        self.client = GeminiClient(settings.gemini_api_key, backend=settings.resolved_gemini_backend, timeout=120,
                                   transport=transport)
        self.poll_seconds = poll_seconds

    def _call(self, model: str, method: str, body: dict, kind: str) -> tuple[dict, str]:
        try:
            r, used = self.client.call_model(model, method, body, kind)
        except GeminiHTTPError as exc:
            raise MediaError(f"Gemini API error HTTP {exc.status}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise MediaError(f"Gemini API unreachable: {type(exc).__name__}") from exc
        if r.status_code >= 400:
            raise MediaError(f"Gemini API error HTTP {r.status_code}: {GeminiClient.error_message(r)}")
        return r.json(), used

    def generate_image(self, prompt: str, *, aspect_ratio: str, brand: dict) -> MediaResult:
        data, model = self._call(self.settings.gemini_image_model, "generateContent", {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}},
        }, "image")
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return MediaResult(base64.b64decode(inline["data"]),
                                       inline.get("mimeType") or inline.get("mime_type") or "image/png", self.name, model)
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "no image in response"
        raise MediaError(f"Image generation returned no image ({reason})")

    def _poll(self, model: str, name: str) -> dict:
        try:
            if self.client.base == VERTEX:  # Vertex AI polls Veo operations through fetchPredictOperation
                r = self.client.request("POST", f"models/{model}:fetchPredictOperation", {"operationName": name})
            else:
                r = self.client.request("GET", name)
        except httpx.HTTPError as exc:
            raise MediaError(f"Gemini API unreachable while polling: {type(exc).__name__}") from exc
        if r.status_code >= 400:
            raise MediaError(f"Polling failed HTTP {r.status_code}: {GeminiClient.error_message(r)}")
        return r.json()

    def generate_video(self, prompt: str, *, aspect_ratio: str, brand: dict) -> MediaResult:
        op, model = self._call(self.settings.gemini_video_model, "predictLongRunning", {
            "instances": [{"prompt": prompt}],
            "parameters": {"aspectRatio": aspect_ratio, "sampleCount": 1},
        }, "video")
        name = op.get("name")
        if not name:
            raise MediaError("Video generation did not return an operation")
        deadline = time.monotonic() + self.settings.video_timeout_seconds
        while not op.get("done"):
            if time.monotonic() > deadline:
                raise MediaError("Video generation timed out")
            time.sleep(self.poll_seconds)
            op = self._poll(model, name)
        if op.get("error"):
            raise MediaError(f"Video generation failed: {op['error'].get('message', op['error'])}")
        resp = op.get("response", {})
        videos = resp.get("videos") or []  # Vertex AI shape: inline bytes (or a Cloud Storage URI)
        if videos:
            if videos[0].get("bytesBase64Encoded"):
                return MediaResult(base64.b64decode(videos[0]["bytesBase64Encoded"]),
                                   videos[0].get("mimeType", "video/mp4"), self.name, model)
            raise MediaError("Veo returned a Cloud Storage URI; configure the output without storageUri to get bytes")
        # Field names differ between API/SDK versions; accept both shapes.
        samples = (resp.get("generateVideoResponse", {}).get("generatedSamples")
                   or resp.get("generatedVideos") or resp.get("generated_videos") or [])
        uri = samples[0].get("video", {}).get("uri") if samples else None
        if not uri:
            raise MediaError("Video generation finished without a video (it may have been filtered)")
        try:
            v = self.client._client.get(uri)
        except httpx.HTTPError as exc:
            raise MediaError(f"Video download failed: {type(exc).__name__}") from exc
        if v.status_code >= 400:
            raise MediaError(f"Video download failed HTTP {v.status_code}")
        return MediaResult(v.content, v.headers.get("content-type", "video/mp4").split(";")[0], self.name, model)
