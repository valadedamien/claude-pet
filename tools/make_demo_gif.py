#!/usr/bin/env python3
"""Regenerates assets/demo.gif and assets/demo-hidden.gif straight from
src/pet.html — no real screen recording, just a headless browser cycling
through window.setPetState(...)/setPetHidden(...) and a frame grab per step.

One-time setup (a throwaway venv is fine, this isn't a runtime dependency of
the app itself):

    python3 -m venv /tmp/gifenv
    /tmp/gifenv/bin/pip install playwright Pillow
    /tmp/gifenv/bin/python3 -m playwright install chromium

Then, from the repo root:

    /tmp/gifenv/bin/python3 tools/make_demo_gif.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image
import io

REPO_ROOT = Path(__file__).resolve().parent.parent
PET_HTML = (REPO_ROOT / "src" / "pet.html").as_uri()
ASSETS = REPO_ROOT / "assets"

STATES = [
    # (state, tool, frame_count, frame_duration_ms)
    ("idle", "", 2, 900),
    ("editing", "Edit", 2, 650),
    ("waiting", "Bash", 2, 750),
    ("sad", "", 2, 900),
    ("done", "", 6, 180),
]


def capture(hidden, viewport):
    frames = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=viewport, device_scale_factor=3)
        page.goto(PET_HTML)
        page.wait_for_timeout(200)
        if hidden:
            page.evaluate("window.setPetHidden(true)")
            page.wait_for_timeout(150)

        for state, tool, frame_count, frame_dur in STATES:
            page.evaluate(f"window.setPetState({state!r}, {tool!r})")
            for _ in range(frame_count):
                page.wait_for_timeout(frame_dur)
                png_bytes = page.screenshot(omit_background=True)
                img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                frames.append((img, frame_dur))

        browser.close()
    return frames


def crop_to_content(imgs, pad=12):
    # Union bounding box across all frames (not per-frame) so the crop is
    # identical every frame — cropping each frame to its own content would
    # make the character jitter/shift as the visible pixels change shape.
    union_box = None
    for im in imgs:
        box = im.getbbox()
        if box is None:
            continue
        union_box = box if union_box is None else (
            min(union_box[0], box[0]), min(union_box[1], box[1]),
            max(union_box[2], box[2]), max(union_box[3], box[3]),
        )
    union_box = (
        max(union_box[0] - pad, 0), max(union_box[1] - pad, 0),
        min(union_box[2] + pad, imgs[0].width), min(union_box[3] + pad, imgs[0].height),
    )
    return [im.crop(union_box) for im in imgs]


def save_gif(imgs, durations, out_path):
    # A naive per-frame quantize gives each frame its OWN adaptive palette —
    # index 0 might be the padding/background color in one frame but the
    # badge's actual fill color in another (whichever's most common in that
    # frame). Hardcoding transparency=0 then makes THAT frame's real fill
    # color vanish instead of its padding. Building one shared palette from
    # every frame combined, with a dedicated reserved index for
    # transparency, keeps that index meaning the same thing everywhere.
    w, h = imgs[0].size
    strip = Image.new("RGB", (w, h * len(imgs)), (255, 255, 255))
    for i, im in enumerate(imgs):
        strip.paste(im, (0, i * h), im)
    pal_img = strip.quantize(colors=255, method=Image.MEDIANCUT)
    transparent_index = 255

    quantized = []
    for im in imgs:
        rgb = Image.new("RGB", im.size, (255, 255, 255))
        rgb.paste(im, (0, 0), im)
        q = rgb.quantize(palette=pal_img, dither=Image.NONE)
        alpha = im.split()[3]
        mask = alpha.point(lambda a: 255 if a == 0 else 0)
        q.paste(transparent_index, mask=mask)
        quantized.append(q)

    quantized[0].save(
        out_path,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        disposal=2,
        transparency=transparent_index,
    )
    print(f"wrote {out_path} ({len(quantized)} frames, size={quantized[0].size})")


def make_gif(hidden, viewport, out_path):
    frames = capture(hidden, viewport)
    imgs = crop_to_content([f[0] for f in frames])
    durations = [f[1] for f in frames]
    save_gif(imgs, durations, out_path)


if __name__ == "__main__":
    make_gif(False, {"width": 190, "height": 210}, ASSETS / "demo.gif")
    make_gif(True, {"width": 190, "height": 60}, ASSETS / "demo-hidden.gif")
