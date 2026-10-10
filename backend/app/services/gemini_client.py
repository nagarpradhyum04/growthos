"""Shared Google Gemini HTTP client: endpoint selection and model discovery.

Why: Google AI Studio and Vertex AI express mode both issue "AQ." keys now, so the key prefix can't pick the
endpoint, and Gemini model ids get retired (a retired id returns HTTP 404). This client
- uses Google AI Studio by default and falls back to Vertex AI only when AI Studio rejects the key (401/403),
  unless GEMINI_BACKEND forces one;
- on a 404 for a model, lists the models this key can use and retries once with the best current one of the
  same kind (text / image / video), logging which model it switched to.
"""
import logging
import re

import httpx

logger = logging.getLogger(__name__)
AI_STUDIO = "https://generativelanguage.googleapis.com/v1beta"
VERTEX = "https://aiplatform.googleapis.com/v1/publishers/google"
_EXCLUDE_TEXT = re.compile(r"image|tts|audio|live|embedding|vision|veo|imagen|aqa|robotics|computer-use|learnlm|gemma", re.I)


class GeminiHTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _version(name: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", name.split("/")[-1])
    return float(m.group(1)) if m else 0.0


def pick_model(models: list[dict], kind: str) -> str | None:
    """Best current model id of a kind from a ListModels response."""
    def ok(m, method):
        return method in (m.get("supportedGenerationMethods") or [])

    names = []
    for m in models:
        mid = m.get("name", "").split("/")[-1]
        if kind == "text" and ok(m, "generateContent") and not _EXCLUDE_TEXT.search(mid):
            names.append(mid)
        elif kind == "image" and ok(m, "generateContent") and "image" in mid and "imagen" not in mid:
            names.append(mid)
        elif kind == "video" and "veo" in mid and ok(m, "predictLongRunning"):
            names.append(mid)
    if not names:
        return None

    def score(mid: str):
        stable = "preview" not in mid and "exp" not in mid
        if kind == "text":  # prefer fast "flash" models (not lite), then lite, then pro
            tier = 2 if "flash" in mid and "lite" not in mid else 1 if "flash" in mid else 0
            return (tier, "latest" not in mid, _version(mid), stable)
        return (_version(mid), "flash" in mid, stable)

    return max(names, key=score)


class GeminiClient:
    def __init__(self, api_key: str, *, backend: str = "auto", timeout: float = 60.0,
                 transport: httpx.BaseTransport | None = None, base_url: str | None = None):
        if not api_key:
            raise GeminiHTTPError(401, "GEMINI_API_KEY is not set")
        self.api_key, self.backend = api_key, backend
        self.base = base_url or (VERTEX if backend == "vertex" else AI_STUDIO)
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True,
                                    headers={"x-goog-api-key": api_key})
        self._models: list[dict] | None = None
        self.switched: dict[str, str] = {}  # configured model -> model actually used

    # -------------------------------------------------- transport
    def request(self, method: str, path: str, json: dict | None = None) -> httpx.Response:
        r = self._client.request(method, f"{self.base}/{path}", json=json)
        if r.status_code in (401, 403) and self.backend == "auto" and self.base == AI_STUDIO:
            alt = self._client.request(method, f"{VERTEX}/{path}", json=json)
            if alt.status_code not in (401, 403):
                logger.warning("Gemini key rejected by Google AI Studio but accepted by Vertex AI; using Vertex AI")
                self.base = VERTEX
                return alt
        return r

    def list_models(self) -> list[dict]:
        if self._models is not None:
            return self._models
        models: list[dict] = []
        if self.base == AI_STUDIO:
            token = ""
            for _ in range(10):
                r = self._client.get(f"{AI_STUDIO}/models", params={"pageSize": 1000, **({"pageToken": token} if token else {})})
                if r.status_code >= 400:
                    break
                data = r.json()
                models += data.get("models", [])
                token = data.get("nextPageToken", "")
                if not token:
                    break
        self._models = models
        return models

    # -------------------------------------------------- model calls with 404 fallback
    def call_model(self, model: str, method: str, body: dict, kind: str) -> tuple[httpx.Response, str]:
        model = self.switched.get(model, model)
        r = self.request("POST", f"models/{model}:{method}", body)
        if r.status_code == 404:
            alt = pick_model(self.list_models(), kind)
            if alt and alt != model:
                logger.warning("Gemini model %s is not available (404); switching to %s", model, alt)
                r2 = self.request("POST", f"models/{alt}:{method}", body)
                if r2.status_code != 404:
                    self.switched[model] = alt
                    return r2, alt
            available = [m["name"].split("/")[-1] for m in self.list_models()
                         if (kind == "video") == ("veo" in m.get("name", ""))][:12]
            raise GeminiHTTPError(404, f"Model '{model}' was not found for this key (it may be retired)."
                                  + (f" Models your key can use: {', '.join(available)}" if available else ""))
        return r, model

    @staticmethod
    def error_message(r: httpx.Response) -> str:
        try:
            return (r.json().get("error") or {}).get("message", "")[:300]
        except ValueError:
            return r.text[:300]
