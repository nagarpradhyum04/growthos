"""MOCK MEDIA ADAPTER — offline previews so the Social Studio works without an API key.

Images: an SVG poster with the post's real headline/brand. Video: an animated SVG storyboard of the
video prompt's scenes. Both are clearly labeled as mock previews; set MEDIA_PROVIDER=gemini for real
Nano Banana images and Veo videos.
"""
import html
import re
import textwrap

from app.services.media import MediaProvider, MediaResult

PALETTE = ["#1c1b19", "#efe9dd", "#b8a07e"]


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    lines = textwrap.wrap(text, width)[:max_lines]
    return [html.escape(line) for line in lines]


def _size(aspect: str, base: int = 1080) -> tuple[int, int]:
    try:
        w, h = (int(x) for x in aspect.split(":"))
    except ValueError:
        w, h = 1, 1
    return (base, int(base * h / w)) if w >= h else (int(base * w / h), base) if False else (base * w // max(w, h), base * h // max(w, h))


class MockMediaProvider(MediaProvider):
    name = "mock"

    def generate_image(self, prompt: str, *, aspect_ratio: str, brand: dict) -> MediaResult:
        w, h = _size(aspect_ratio)
        headline = _wrap(brand.get("headline") or brand.get("company", ""), 22, 4)
        company = html.escape(brand.get("company", ""))
        tspans = "".join(f'<tspan x="80" dy="{0 if i == 0 else 92}">{line}</tspan>' for i, line in enumerate(headline))
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<rect width="{w}" height="{h}" fill="{PALETTE[1]}"/>
<rect x="40" y="40" width="{w - 80}" height="{h - 80}" fill="none" stroke="{PALETTE[0]}" stroke-width="3"/>
<circle cx="{w - 220}" cy="260" r="150" fill="{PALETTE[2]}" opacity=".55"/>
<text x="80" y="140" font-family="monospace" font-size="26" letter-spacing="6" fill="{PALETTE[0]}">{company.upper()}</text>
<text x="80" y="{h // 2 - 60}" font-family="Georgia, serif" font-size="80" font-weight="700" fill="{PALETTE[0]}">{tspans}</text>
<rect x="0" y="{h - 110}" width="{w}" height="110" fill="{PALETTE[0]}"/>
<text x="80" y="{h - 48}" font-family="monospace" font-size="24" letter-spacing="3" fill="{PALETTE[1]}">MOCK PREVIEW · SET MEDIA_PROVIDER=gemini FOR NANO BANANA</text>
</svg>"""
        return MediaResult(svg.encode(), "image/svg+xml", self.name, "mock-image")

    def generate_video(self, prompt: str, *, aspect_ratio: str, brand: dict) -> MediaResult:
        w, h = _size(aspect_ratio)
        scenes = [s.strip() for s in re.split(r"(?:Scene \d+:|\n|;)", prompt) if len(s.strip()) > 12][:4] or [prompt[:120]]
        n = len(scenes)
        dur = 3 * n
        frames = []
        for i, scene in enumerate(scenes):
            lines = "".join(f'<tspan x="70" dy="{0 if j == 0 else 62}">{t}</tspan>'
                            for j, t in enumerate(_wrap(scene, 26, 6)))
            # Each scene is visible for its 3-second slot of the loop.
            start, end = i / n, (i + 1) / n
            frames.append(f"""<g opacity="0"><animate attributeName="opacity" dur="{dur}s" repeatCount="indefinite"
 keyTimes="0;{start:.3f};{start + 0.001:.3f};{end:.3f};{min(end + 0.001, 1):.3f};1" values="0;0;1;1;0;0"/>
<text x="70" y="{h // 2 - 120}" font-family="Georgia, serif" font-size="54" fill="{PALETTE[1]}">{lines}</text>
<text x="70" y="{h - 220}" font-family="monospace" font-size="26" fill="{PALETTE[2]}">SCENE {i + 1}/{n}</text></g>""")
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<rect width="{w}" height="{h}" fill="{PALETTE[0]}"/>
<text x="70" y="140" font-family="monospace" font-size="28" letter-spacing="6" fill="{PALETTE[2]}">{html.escape(brand.get("company", "")).upper()}</text>
{''.join(frames)}
<rect x="70" y="{h - 160}" width="{w - 140}" height="6" fill="#3a3834"/>
<rect x="70" y="{h - 160}" width="0" height="6" fill="{PALETTE[2]}"><animate attributeName="width" from="0" to="{w - 140}" dur="{dur}s" repeatCount="indefinite"/></rect>
<text x="70" y="{h - 90}" font-family="monospace" font-size="22" letter-spacing="2" fill="{PALETTE[1]}">MOCK STORYBOARD · SET MEDIA_PROVIDER=gemini FOR A REAL VEO VIDEO</text>
</svg>"""
        return MediaResult(svg.encode(), "image/svg+xml", self.name, "mock-storyboard")
