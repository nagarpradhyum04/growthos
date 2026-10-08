"""Fetches a lead's public website (homepage + /about) and extracts readable text.

Includes basic SSRF protection: only http(s), and hostnames must resolve to public IPs.
"""
import html
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from app.services.search.base import EvidenceDoc, SearchError

MAX_BYTES = 1_000_000
MAX_TEXT_CHARS = 6000
USER_AGENT = "GrowthOS-Research/1.0 (+public company research)"

_SCRIPT_RE = re.compile(r"<(script|style|noscript|svg|nav|footer)[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_META_DESC_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', re.I)


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def _assert_public_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SearchError(f"Unsupported URL: {url}")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise SearchError(f"Could not resolve {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise SearchError(f"Refusing to fetch non-public address for {parsed.hostname}")


def html_to_text(raw_html: str) -> tuple[str, str]:
    title_match = _TITLE_RE.search(raw_html)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""
    desc_match = _META_DESC_RE.search(raw_html)
    body = _SCRIPT_RE.sub(" ", raw_html)
    body = _TAG_RE.sub(" ", body)
    text = html.unescape(re.sub(r"\s+", " ", body)).strip()
    if desc_match:
        text = html.unescape(desc_match.group(1)).strip() + " " + text
    return title, text[:MAX_TEXT_CHARS]


class WebsiteFetcher:
    def __init__(self, timeout_seconds: float = 10.0, transport: httpx.BaseTransport | None = None,
                 check_host: bool = True):
        self._timeout = timeout_seconds
        self._transport = transport
        self._check_host = check_host

    def fetch_site(self, website: str) -> list[EvidenceDoc]:
        base = normalize_url(website)
        if not base:
            return []
        docs = [self._fetch(base)]
        try:
            docs.append(self._fetch(urljoin(base if base.endswith("/") else base + "/", "about")))
        except SearchError:
            pass  # An about page is optional.
        return [d for d in docs if d.text]

    def _fetch(self, url: str) -> EvidenceDoc:
        # Redirects are followed manually so every hop is checked against private addresses.
        try:
            with httpx.Client(
                timeout=self._timeout, headers={"User-Agent": USER_AGENT}, transport=self._transport
            ) as client:
                for _ in range(4):
                    if self._check_host:
                        _assert_public_host(url)
                    response = client.get(url)
                    if response.is_redirect and "location" in response.headers:
                        url = urljoin(url, response.headers["location"])
                        continue
                    break
                else:
                    raise SearchError(f"Too many redirects for {url}")
        except httpx.HTTPError as exc:
            raise SearchError(f"Could not fetch {url}: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise SearchError(f"Could not fetch {url}: HTTP {response.status_code}")
        if "html" not in response.headers.get("content-type", "html"):
            raise SearchError(f"{url} is not an HTML page")
        title, text = html_to_text(response.content[:MAX_BYTES].decode(response.encoding or "utf-8", "replace"))
        return EvidenceDoc(url=url, title=title, text=text, source_type="website")
