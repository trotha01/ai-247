"""skia-python templates: headline card, citation card, bar chart, scrolling ticker, badge."""
from __future__ import annotations

import skia

W, H, FPS = 1280, 720, 30
BG1, BG2 = 0xFF0B1220, 0xFF16264A
INK, MUTED, ACCENT, WARN = 0xFFF2F5FA, 0xFF9FB0CC, 0xFF4CC2FF, 0xFFE5484D

_fonts: dict = {}


def font(size: float, bold: bool = False) -> skia.Font:
    key = (size, bold)
    if key not in _fonts:
        style = skia.FontStyle.Bold() if bold else skia.FontStyle.Normal()
        tf = skia.FontMgr.RefDefault().legacyMakeTypeface("DejaVu Sans", style) or skia.Typeface.MakeDefault()
        _fonts[key] = skia.Font(tf, size)
    return _fonts[key]


def paint(color, alpha: float = 1.0, **kw) -> skia.Paint:
    c = skia.Color4f.FromColor(color)
    return skia.Paint(Color4f=skia.Color4f(c.fR, c.fG, c.fB, c.fA * alpha), AntiAlias=True, **kw)


def text(canvas, s, x, y, size, color=INK, bold=False, alpha=1.0):
    canvas.drawString(s, x, y, font(size, bold), paint(color, alpha))


def wrap(s: str, size: float, max_w: float, bold=False, max_lines=6) -> list[str]:
    f, lines, cur = font(size, bold), [], ""
    for w in s.split():
        trial = f"{cur} {w}".strip()
        if f.measureText(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".") + "..."
    return lines


def background(canvas):
    shader = skia.GradientShader.MakeLinear(
        [(0, 0), (W, H)], [BG1, BG2])
    canvas.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=shader))


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


LABEL = "AI NEWS 24/7  |  Day 0 test bulletin"


def chrome(canvas, scene_t: float, global_frame: int, ticker_text: str, dur: float = 6.0):
    """Elements present on every segment: channel label, AI badge, progress bar, ticker."""
    text(canvas, LABEL, 40, 52, 22, MUTED, True)
    canvas.drawRoundRect(skia.Rect.MakeXYWH(W - 250, 26, 210, 36), 8, 8, paint(WARN))
    text(canvas, "AI-GENERATED", W - 236, 52, 20, INK, True)
    canvas.drawRect(skia.Rect.MakeXYWH(0, 0, W * min(1.0, scene_t / dur), 5), paint(ACCENT))
    # ticker
    canvas.drawRect(skia.Rect.MakeXYWH(0, H - 56, W, 56), paint(0xFF050A14))
    canvas.drawRect(skia.Rect.MakeXYWH(0, H - 56, W, 3), paint(ACCENT))
    f = font(24, True)
    tw = f.measureText(ticker_text)
    x = -((global_frame * 3) % int(tw)) if tw else 0
    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(0, H - 53, W, 53))
    while x < W:
        canvas.drawString(ticker_text, x, H - 18, f, paint(INK))
        x += tw
    canvas.restore()


def headline_card(canvas, scene, t):
    a = ease(t / 0.5)
    y_off = (1 - a) * 40
    text(canvas, f"HEADLINE {scene['story'] + 1}", 60, 150, 24, ACCENT, True, a)
    lines = wrap(scene["headline"], 54, W - 120, True, 5)
    y = 230 + y_off
    for ln in lines:
        text(canvas, ln, 60, y, 54, INK, True, a)
        y += 70
    canvas.drawRoundRect(skia.Rect.MakeXYWH(60, H - 150, 760, 44), 8, 8, paint(0xFF1E3A66, a))
    text(canvas, f"Source: {scene['citation']['source']}  ({scene['citation']['published'] or 'date n/a'})",
         76, H - 119, 24, INK, False, a)


def citation_card(canvas, scene, t):
    a = ease(t / 0.4)
    c = scene["citation"]
    canvas.drawRoundRect(skia.Rect.MakeXYWH(50, 100, W - 100, H - 190), 18, 18, paint(0xFF0F1B33, 0.92))
    text(canvas, "SOURCE CITATION", 80, 150, 24, ACCENT, True, a)
    text(canvas, c["source"], 80, 215, 52, INK, True, a)
    text(canvas, f"Published: {c['published'] or 'date n/a'}", 80, 255, 24, MUTED, False, a)
    y = 320
    for ln in wrap("“" + scene["claims"][0] + "”", 38, W - 190, False, 4):
        text(canvas, ln, 80, y, 38, INK, False, a)
        y += 50
    y = H - 140
    for ln in wrap(c["url"], 22, W - 190, False, 2):
        text(canvas, ln, 80, y, 22, ACCENT, False, a)
        y += 28
    text(canvas, "Quoted from the source text above.", 80, H - 95, 20, MUTED, False, a)


def bar_chart(canvas, scene, t):
    a = ease(t / 0.4)
    text(canvas, scene["chart"]["title"], 60, 140, 40, INK, True, a)
    data = scene["chart"]["data"]
    mx = max([v for _, v in data] or [1])
    y = 190
    for i, (label, v) in enumerate(data):
        grow = ease((t - 0.3 - 0.12 * i) / 0.6)
        text(canvas, label, 60, y + 32, 24, INK, False, a)
        bw = (W - 560) * v / mx * grow
        canvas.drawRoundRect(skia.Rect.MakeXYWH(360, y, max(bw, 2), 40), 6, 6, paint(ACCENT, a))
        text(canvas, str(v), 370 + bw, y + 32, 24, INK, True, a * grow)
        y += 62
    text(canvas, "Source: " + scene["chart"]["source"], 60, H - 80, 20, MUTED, False, a)
    text(canvas, scene["title"], 60, 100, 26, MUTED, True, a)


def title_card(canvas, scene, t):
    a = ease(t / 0.5)
    for k, ln in enumerate(wrap(scene["title"], 60, W - 140, True, 3)):
        text(canvas, ln, 70, 280 + 76 * k, 60, INK, True, a)
    for k, ln in enumerate(wrap(scene["subtitle"], 30, W - 140, False, 3)):
        text(canvas, ln, 70, 440 + 42 * k, 30, MUTED, False, a)


def sentence_card(canvas, scene, t):
    """One aired sentence, with its source citation always on screen."""
    a = ease(t / 0.4)
    c = scene["citation"]
    text(canvas, scene["headline"], 60, 125, 26, MUTED, True, a)
    y = 215
    for ln in wrap(scene["claims"][0], 44, W - 120, False, 6):
        text(canvas, ln, 60, y, 44, INK, False, a)
        y += 58
    canvas.drawRoundRect(skia.Rect.MakeXYWH(50, H - 190, W - 100, 118), 14, 14, paint(0xFF0F1B33, 0.95))
    text(canvas, f"SOURCE: {c['source']}  ({c['published'] or 'date n/a'})", 72, H - 150, 26, ACCENT, True, a)
    for k, ln in enumerate(wrap(c["url"], 21, W - 150, False, 2)):
        text(canvas, ln, 72, H - 112 + 26 * k, 21, INK, False, a)


def source_card(canvas, scene, t):
    a = ease(t / 0.4)
    c = scene["citation"]
    text(canvas, "SOURCE", 60, 150, 26, ACCENT, True, a)
    text(canvas, c["source"], 60, 230, 64, INK, True, a)
    text(canvas, f"Published: {c['published'] or 'date n/a'}", 60, 285, 28, MUTED, False, a)
    for k, ln in enumerate(wrap(c["url"], 26, W - 120, False, 3)):
        text(canvas, ln, 60, 360 + 36 * k, 26, ACCENT, False, a)
    text(canvas, scene["headline"], 60, H - 120, 26, MUTED, False, a)


def list_card(canvas, scene, t):
    """Rundown (intro) / recap: numbered headlines with their sources."""
    a = ease(t / 0.5)
    text(canvas, scene["title"], 60, 130, 44, INK, True, a)
    y = 190
    for i, (src, head) in enumerate(scene["items"]):
        text(canvas, f"{i + 1}. {head[:62]}  [{src}]", 60, y, 24, INK, False, a)
        y += 36 if len(scene["items"]) > 10 else 42
    text(canvas, "Every sentence in this episode shows the source it came from.", 60, H - 85, 20, MUTED, False, a)


def standby_card(canvas, scene, t):
    a = ease(t / 0.5)
    text(canvas, scene["title"], 70, 300, 60, INK, True, a)
    for k, ln in enumerate(wrap(scene["subtitle"], 30, W - 140, False, 3)):
        text(canvas, ln, 70, 380 + 42 * k, 30, MUTED, False, a)


def draw_scene(canvas, scene, scene_t: float, global_frame: int, ticker: str):
    background(canvas)
    kind = scene["kind"]
    if kind in ("sentence",):
        sentence_card(canvas, scene, scene_t)
    elif kind == "source":
        source_card(canvas, scene, scene_t)
    elif kind in ("rundown", "recap"):
        list_card(canvas, scene, scene_t)
    elif kind == "standby":
        standby_card(canvas, scene, scene_t)
    elif kind == "headline":
        headline_card(canvas, scene, scene_t)
    elif kind == "citation":
        citation_card(canvas, scene, scene_t)
    elif kind == "chart":
        bar_chart(canvas, scene, scene_t)
    else:
        title_card(canvas, scene, scene_t)
    chrome(canvas, scene_t, global_frame, ticker, scene.get("duration", 6.0))


def new_surface():
    return skia.Surface(W, H)


def frame_bytes(surface) -> bytes:
    img = surface.makeImageSnapshot()
    return img.tobytes()  # N32: BGRA on little-endian Linux
