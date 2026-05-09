"""Poster generation: fetch base art, overlay progress bar + text, cache to disk.

Cache key is (item_id, progress_bucket) where bucket = floor(progress / 5) * 5.
That gives at most 21 PNGs per item lifecycle (0, 5, 10, ..., 100), which is fine.
"""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger(__name__)


class PosterGenerator:
    """Generates progress-overlaid posters and caches them on disk."""

    def __init__(
        self,
        cache_dir: Path,
        size: tuple[int, int] = (400, 600),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.size = size
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = client or httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        self._owns_client = client is None
        self._art_cache: dict[str, bytes] = {}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_or_generate(
        self,
        item_id: str,
        progress_percent: float,
        eta_seconds: int | None,
        status: str,
        art_url: str | None,
        title: str,
    ) -> Path:
        bucket = int(progress_percent // 5) * 5
        cache_key = f"{safe_filename_id(item_id)}__p{bucket:03d}__{status}.png"
        out_path = self.cache_dir / cache_key

        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path

        base = await self._load_base_art(item_id, art_url)
        rendered = self._render(
            base=base,
            progress_percent=progress_percent,
            eta_seconds=eta_seconds,
            status=status,
            title=title,
        )
        rendered.save(out_path, format="PNG", optimize=True)
        return out_path

    async def _load_base_art(self, item_id: str, art_url: str | None) -> Image.Image:
        """Fetch base poster art. Falls back to solid placeholder."""
        if art_url:
            cached = self._art_cache.get(item_id)
            if not cached:
                try:
                    r = await self._client.get(art_url)
                    r.raise_for_status()
                    cached = r.content
                    self._art_cache[item_id] = cached
                except httpx.HTTPError as e:
                    log.warning("Art fetch failed for %s (%s): %s", item_id, art_url, e)

            if cached:
                try:
                    img = Image.open(io.BytesIO(cached)).convert("RGB")
                    return img.resize(self.size, Image.Resampling.LANCZOS)
                except Exception as e:  # noqa: BLE001 — Pillow can throw various
                    log.warning("Art decode failed for %s: %s", item_id, e)

        return self._placeholder()

    def _placeholder(self) -> Image.Image:
        return Image.new("RGB", self.size, color=(20, 30, 40))

    def _render(
        self,
        base: Image.Image,
        progress_percent: float,
        eta_seconds: int | None,
        status: str,
        title: str,
    ) -> Image.Image:
        img = base.copy()
        w, h = img.size

        # Subtle bottom-shadow for legibility
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rectangle([0, h - 140, w, h], fill=(0, 0, 0, 180))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
        img = Image.alpha_composite(img.convert("RGBA"), shadow).convert("RGB")

        d = ImageDraw.Draw(img)
        font_lg = _font(28)
        font_sm = _font(18)

        # Status badge top-right
        badge_text, badge_color = _status_badge(status)
        bbox = d.textbbox((0, 0), badge_text, font=font_sm)
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        bx, by = w - bw - 28, 16
        d.rounded_rectangle(
            [bx - 12, by - 6, bx + bw + 12, by + bh + 10], radius=8, fill=badge_color
        )
        d.text((bx, by), badge_text, fill=(255, 255, 255), font=font_sm)

        # Progress bar near bottom
        bar_x0, bar_x1 = 32, w - 32
        bar_y0, bar_y1 = h - 64, h - 50
        d.rounded_rectangle(
            [bar_x0, bar_y0, bar_x1, bar_y1], radius=6, fill=(60, 60, 60)
        )
        fill_width = int((bar_x1 - bar_x0) * (progress_percent / 100.0))
        if fill_width > 4:
            d.rounded_rectangle(
                [bar_x0, bar_y0, bar_x0 + fill_width, bar_y1],
                radius=6,
                fill=(60, 200, 130),
            )

        # Progress text + ETA
        pct_text = f"{progress_percent:.0f}%"
        eta_text = _human_eta(eta_seconds) if eta_seconds is not None else ""
        bottom_text = f"{pct_text}   ·   ETA  {eta_text}" if eta_text else pct_text
        d.text((32, h - 110), title[:40], fill=(255, 255, 255), font=font_lg)
        d.text((32, h - 30), bottom_text, fill=(220, 220, 220), font=font_sm)

        return img


def safe_filename_id(item_id: str) -> str:
    """Sanitise item_id for safe use in a filename."""
    h = hashlib.sha1(item_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"{item_id.replace('/', '_').replace(':', '_')[:50]}__{h}"


# Back-compat alias for tests
_safe_id = safe_filename_id


def _font(size: int) -> ImageFont.ImageFont:
    """Try a few common fonts, fall back to PIL default."""
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _status_badge(status: str) -> tuple[str, tuple[int, int, int, int]]:
    return {
        "queued": ("QUEUED", (140, 140, 140, 220)),
        "downloading": ("LIVE", (60, 200, 130, 220)),
        "completed": ("READY", (30, 144, 255, 220)),
        "failed": ("FAILED", (220, 60, 60, 220)),
        "paused": ("PAUSED", (200, 160, 60, 220)),
    }.get(status, ("PENDING", (140, 140, 140, 220)))


def _human_eta(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"
