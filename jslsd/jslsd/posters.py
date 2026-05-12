"""Poster generation: fetch base art, overlay progress bar + text, cache to disk.

Cache key is (item_id, progress_bucket) where bucket = floor(progress / 5) * 5.
That gives at most 21 PNGs per item lifecycle (0, 5, 10, ..., 100), which is fine.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
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
        accent_color: str = "#ff00d4",
        surface_color: str = "#101820",
    ) -> None:
        self.cache_dir = cache_dir
        self.size = size
        self.accent_rgb = _hex_to_rgb(accent_color)
        self.surface_rgb = _hex_to_rgb(surface_color)
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
        subtitle: str | None = None,
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
            subtitle=subtitle,
        )
        # Atomic write: render to temp file in the same dir, then rename. Prevents
        # a half-written PNG from being served if the process dies mid-save (the
        # >0 size check above would happily return a truncated file otherwise).
        tmp_path = out_path.with_suffix(out_path.suffix + f".tmp.{os.getpid()}")
        try:
            rendered.save(tmp_path, format="PNG", optimize=True)
            os.replace(tmp_path, out_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return out_path

    async def _load_base_art(self, item_id: str, art_url: str | None) -> Image.Image:
        """Fetch base poster art. Falls back to solid placeholder.

        Art is cached by URL so multiple items pointing at the same series
        poster only trigger one upstream fetch.
        """
        if art_url:
            cached = self._art_cache.get(art_url)
            if not cached:
                try:
                    r = await self._client.get(art_url)
                    r.raise_for_status()
                    cached = r.content
                    self._art_cache[art_url] = cached
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
        subtitle: str | None = None,
    ) -> Image.Image:
        img = base.copy().convert("RGBA")
        w, h = img.size

        # Gradient scrim along the bottom third for legibility — top transparent,
        # bottom near-opaque using configured surface_color.
        scrim_h = int(h * 0.42)
        scrim = Image.new("RGBA", (w, scrim_h), (0, 0, 0, 0))
        sr, sg, sb = self.surface_rgb
        for y in range(scrim_h):
            alpha = int(235 * (y / scrim_h) ** 1.6)
            ImageDraw.Draw(scrim).line([(0, y), (w, y)], fill=(sr, sg, sb, alpha))
        img.paste(scrim, (0, h - scrim_h), scrim)

        d = ImageDraw.Draw(img)
        font_lg = _font(30)
        font_md = _font(22)
        font_sm = _font(18)

        # Status badge top-right
        badge_text, badge_color = _status_badge(status)
        bbox = d.textbbox((0, 0), badge_text, font=font_sm)
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        bx, by = w - bw - 28, 16
        d.rounded_rectangle(
            [bx - 12, by - 6, bx + bw + 12, by + bh + 10], radius=10, fill=badge_color
        )
        d.text((bx, by), badge_text, fill=(255, 255, 255), font=font_sm)

        # Title (auto-wrap to 2 lines)
        title_lines = _wrap_title(title, font_lg, w - 64, d)
        line_h = font_lg.size + 6
        title_top = h - 168 - (len(title_lines) - 1) * line_h
        for i, line in enumerate(title_lines):
            d.text(
                (32, title_top + i * line_h),
                line,
                fill=(255, 255, 255),
                font=font_lg,
            )

        # Subtitle (e.g. "12 Folgen · Sonarr")
        if subtitle:
            d.text((32, h - 130), subtitle, fill=(210, 210, 210), font=font_sm)

        # Big progress bar — 24px tall, with accent glow.
        bar_x0, bar_x1 = 32, w - 32
        bar_y0, bar_y1 = h - 92, h - 68
        bar_radius = 12

        # Track (dark, inset)
        d.rounded_rectangle(
            [bar_x0, bar_y0, bar_x1, bar_y1],
            radius=bar_radius,
            fill=(28, 28, 36),
            outline=(255, 255, 255, 30),
            width=1,
        )

        fill_width = int((bar_x1 - bar_x0) * (progress_percent / 100.0))
        if fill_width > bar_radius * 2:
            # Soft glow under the fill — same accent, very translucent
            ar, ag, ab = self.accent_rgb
            glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.rounded_rectangle(
                [bar_x0 - 6, bar_y0 - 6, bar_x0 + fill_width + 6, bar_y1 + 6],
                radius=bar_radius + 6,
                fill=(ar, ag, ab, 110),
            )
            glow = glow.filter(ImageFilter.GaussianBlur(radius=8))
            img = Image.alpha_composite(img, glow)
            d = ImageDraw.Draw(img)

            # Solid fill
            d.rounded_rectangle(
                [bar_x0, bar_y0, bar_x0 + fill_width, bar_y1],
                radius=bar_radius,
                fill=(ar, ag, ab, 255),
            )

        # Bottom row: big percent on the left, ETA on the right
        pct_text = f"{progress_percent:.0f}%"
        d.text((32, h - 56), pct_text, fill=(255, 255, 255), font=font_md)

        if eta_seconds is not None:
            eta_text = f"ETA  {_human_eta(eta_seconds)}"
            ebbox = d.textbbox((0, 0), eta_text, font=font_sm)
            ew = ebbox[2] - ebbox[0]
            d.text(
                (w - ew - 32, h - 50),
                eta_text,
                fill=(220, 220, 220),
                font=font_sm,
            )

        return img.convert("RGB")


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


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    s = hex_color.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _wrap_title(text: str, font: ImageFont.ImageFont, max_width: int, d: ImageDraw.ImageDraw) -> list[str]:
    """Naive word-wrap to at most 2 lines, last line truncated with ellipsis."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = d.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= 1:
                break
    if current:
        lines.append(current)
    # Hard-truncate if still >2 lines worth
    if len(lines) > 2:
        lines = lines[:2]
    # Ellipsis on last line if we ran out of space
    if len(lines) == 2:
        remaining_words = words[sum(len(line.split()) for line in lines):]
        if remaining_words:
            last = lines[1]
            while d.textbbox((0, 0), last + "…", font=font)[2] > max_width and " " in last:
                last = last.rsplit(" ", 1)[0]
            lines[1] = last + "…"
    return lines


def _human_eta(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"
