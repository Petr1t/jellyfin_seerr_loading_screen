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
        size: tuple[int, int] = (600, 900),
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

        # Font sizes scale with the shortest side so the layout looks the same
        # whether the poster is 400×600 (legacy) or 600×900 (new default).
        unit = min(w, h) / 600.0
        f_title = _font(int(38 * unit))
        f_pct = _font(int(72 * unit))   # main progress number — was 22, now huge
        f_eta = _font(int(44 * unit))   # ETA — was 18, now reads at thumbnail size
        f_sub = _font(int(22 * unit))
        f_badge = _font(int(26 * unit))

        # Bigger scrim — the bottom half needs to fit a much larger ETA + %.
        scrim_h = int(h * 0.55)
        scrim = Image.new("RGBA", (w, scrim_h), (0, 0, 0, 0))
        sr, sg, sb = self.surface_rgb
        for y in range(scrim_h):
            alpha = int(245 * (y / scrim_h) ** 1.4)
            ImageDraw.Draw(scrim).line([(0, y), (w, y)], fill=(sr, sg, sb, alpha))
        img.paste(scrim, (0, h - scrim_h), scrim)

        d = ImageDraw.Draw(img)
        pad = int(40 * unit)

        # Status badge top-right
        badge_text, badge_color = _status_badge(status)
        bbox = d.textbbox((0, 0), badge_text, font=f_badge)
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        bx = w - bw - pad
        by = pad - int(8 * unit)
        d.rounded_rectangle(
            [bx - int(16 * unit), by - int(8 * unit),
             bx + bw + int(16 * unit), by + bh + int(14 * unit)],
            radius=int(14 * unit), fill=badge_color
        )
        d.text((bx, by), badge_text, fill=(255, 255, 255), font=f_badge)

        # Bottom block layout (bottom-up):
        #   |  72% (huge)            ETA 12m (huge)  |  ← progress row
        #   |======== progress bar ================  |
        #   |  subtitle (12 Folgen · 24.3 GB)        |
        #   |  title (auto-wrap 2 lines)             |
        bar_h = int(44 * unit)
        bar_gap = int(28 * unit)
        bottom_margin = pad + int(8 * unit)
        progress_row_h = max(f_pct.size, f_eta.size)
        bar_y1 = h - bottom_margin - progress_row_h - bar_gap
        bar_y0 = bar_y1 - bar_h
        bar_x0, bar_x1 = pad, w - pad
        bar_radius = bar_h // 2

        # Big progress row UNDER the bar
        pct_y = bar_y1 + bar_gap
        pct_text = f"{progress_percent:.0f}%"
        d.text((pad, pct_y), pct_text, fill=(255, 255, 255), font=f_pct)

        if eta_seconds is not None:
            eta_text = f"ETA  {_human_eta(eta_seconds)}"
            ebbox = d.textbbox((0, 0), eta_text, font=f_eta)
            ew = ebbox[2] - ebbox[0]
            eta_y = pct_y + (f_pct.size - f_eta.size) // 2
            d.text(
                (w - ew - pad, eta_y),
                eta_text,
                fill=(245, 245, 245),
                font=f_eta,
            )

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
            ar, ag, ab = self.accent_rgb
            glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.rounded_rectangle(
                [bar_x0 - 8, bar_y0 - 8, bar_x0 + fill_width + 8, bar_y1 + 8],
                radius=bar_radius + 8,
                fill=(ar, ag, ab, 120),
            )
            glow = glow.filter(ImageFilter.GaussianBlur(radius=10))
            img = Image.alpha_composite(img, glow)
            d = ImageDraw.Draw(img)

            d.rounded_rectangle(
                [bar_x0, bar_y0, bar_x0 + fill_width, bar_y1],
                radius=bar_radius,
                fill=(ar, ag, ab, 255),
            )

        # Subtitle just above the bar
        sub_y = bar_y0 - int(36 * unit)
        if subtitle:
            d.text((pad, sub_y), subtitle, fill=(215, 215, 215), font=f_sub)
            title_baseline = sub_y - int(12 * unit)
        else:
            title_baseline = bar_y0 - int(16 * unit)

        # Title (auto-wrap, anchored above subtitle)
        title_lines = _wrap_title(title, f_title, w - 2 * pad, d)
        line_h = f_title.size + int(8 * unit)
        title_top = title_baseline - len(title_lines) * line_h
        for i, line in enumerate(title_lines):
            d.text(
                (pad, title_top + i * line_h),
                line,
                fill=(255, 255, 255),
                font=f_title,
            )

        return img.convert("RGB")

    async def generate_info_tile(
        self,
        item_id: str,
        kind: str,
        label: str,
        value: str,
        accent: tuple[int, int, int] | None = None,
    ) -> Path:
        """Render a single info tile (label + big value) used for the
        sub-folder detail view. Cached by (item_id, kind, value)."""
        slug = "".join(c if c.isalnum() else "_" for c in value)[:40]
        cache_key = f"{safe_filename_id(item_id)}__tile_{kind}_{slug}.png"
        out_path = self.cache_dir / cache_key
        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path

        w, h = self.size
        unit = min(w, h) / 600.0
        bg = self.surface_rgb
        accent_rgb = accent or self.accent_rgb

        img = Image.new("RGB", (w, h), color=bg)
        d = ImageDraw.Draw(img)

        # Top accent stripe
        d.rectangle([0, 0, w, int(8 * unit)], fill=accent_rgb)

        f_label = _font(int(34 * unit))
        f_value = _font(int(96 * unit))

        # Label centred at the top third
        lb = d.textbbox((0, 0), label, font=f_label)
        lw = lb[2] - lb[0]
        d.text(
            ((w - lw) // 2, int(80 * unit)),
            label.upper(),
            fill=(200, 200, 210),
            font=f_label,
        )

        # Value centred in the middle — auto-shrinks if too wide
        f_actual = f_value
        for size in (96, 84, 72, 60, 48, 40):
            f_actual = _font(int(size * unit))
            vb = d.textbbox((0, 0), value, font=f_actual)
            if vb[2] - vb[0] <= w - int(48 * unit):
                break
        vb = d.textbbox((0, 0), value, font=f_actual)
        vw = vb[2] - vb[0]
        vh = vb[3] - vb[1]
        d.text(
            ((w - vw) // 2, (h - vh) // 2),
            value,
            fill=(255, 255, 255),
            font=f_actual,
        )

        tmp_path = out_path.with_suffix(out_path.suffix + f".tmp.{os.getpid()}")
        try:
            img.save(tmp_path, format="PNG", optimize=True)
            os.replace(tmp_path, out_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return out_path


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
    """Word-wrap to at most 2 lines; only add ellipsis if something is truncated."""
    words = text.split()
    lines: list[str] = []
    current = ""
    used = 0
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = d.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
            used += 1
        else:
            if current:
                lines.append(current)
                current = ""
                if len(lines) >= 2:
                    break
            current = word
            used += 1
    if current and len(lines) < 2:
        lines.append(current)
    elif current:
        used -= 1  # last word didn't fit
    # Ellipsis only if real overflow remains
    if used < len(words) and len(lines) == 2:
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
