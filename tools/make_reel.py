#!/usr/bin/env python3
"""Assemble the project reel from screen recordings.

The edit lives in a script rather than in a timeline, for the same reason the
README image is generated rather than cropped by hand: re-recording a shot then
costs one command instead of an afternoon rebuilding a sequence.

    python tools/make_reel.py --track laps.mkv --bench degraded.mkv -o reel.mp4

`--track` is footage of the display beside a running simulator; `--bench` is the
display alone, fed by tools/sim_telemetry.py with packet loss injected. Both are
expected to be 1080x1350 at 60 fps — see the OBS notes in the README.

Captions are drawn with Pillow and composited as images. This keeps the
typography under control and avoids depending on an ffmpeg built with
libfreetype, which many distributions are not.

Engine audio rides along from the track footage. The bench shot is digital
silence because nothing is running there but a Python script — so the sound
falls away exactly when the car leaves the screen, which marks the change of
subject better than any transition would.
"""

import argparse
import os
import subprocess
import sys

try:
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("needs: pip install imageio-ffmpeg Pillow")

W, H = 1080, 1350
FPS = 60

INK = (233, 239, 242)
MUTED = (140, 163, 172)
ACCENT = (57, 208, 122)
PLATE = (8, 11, 13, 205)

# ─────────────────────────────────────────────────────────────────────────────
# The edit. Timecodes are seconds into the named source and belong to one set of
# takes; re-record and they change. Everything else here is layout.
# ─────────────────────────────────────────────────────────────────────────────

# The bench shot has no simulator above it, so the display is lifted out of its
# sea of black and re-centred — an empty upper half reads as a mistake.
CENTRE_DASH = f"crop={W}:412:0:764,pad={W}:{H}:0:469:black"

# Captions may be a string or a list of lines. Titles may be a string or a
# (title, subtitle) pair.
EDIT = [
    ("track", 29.2, 4.8, "Real-time telemetry - C++/Qt reading Assetto Corsa",
     ("MOTORSPORT TELEMETRY",
      "top: the simulator            bottom: the app I built"), None),
    ("track", 38.0, 6.5, "99% brake - all four wheels locking", None, None),
    ("track", 13.5, 4.0, "Matches the car's own readout, live", None, None),
    # The last beat has no car in it, so it has to say what it is before it can
    # say why it matters. Two captions rather than one long one.
    ("bench", 6.0, 5.0, ["Simulator gone. A test source now feeds the same app",
                         "and it can drop or reorder packets on demand"],
     None, CENTRE_DASH),
    ("bench", 11.0, 5.0, ["15% of packets dropped on purpose",
                          "lost and ooo climb, bad stays zero, nothing stutters"],
     None, CENTRE_DASH),
]
END_CARD_SECONDS = 3.0

END_CARD = [
    ("title", 60, "Motorsport Telemetry", INK, 520),
    ("title", 60, "& Control Stack", INK, 592),
    ("mono", 31, "C++  -  Qt / QML  -  UDP  -  STM32 next", MUTED, 700),
    ("mono", 35, "github.com/Sondacg/motorsport-telemetry", ACCENT, 790),
]


def find_font(kind):
    """Bold sans for headings, bold mono for anything reporting a value."""
    candidates = {
        "title": [r"C:\Windows\Fonts\segoeuib.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                  "/System/Library/Fonts/Helvetica.ttc"],
        "mono": [r"C:\Windows\Fonts\consolab.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
                 "/System/Library/Fonts/Menlo.ttc"],
    }[kind]
    for path in candidates:
        if os.path.exists(path):
            return path
    sys.exit(f"no {kind} font found; add one to find_font()")


def centred(draw, text, font, y, fill):
    draw.text(((W - draw.textlength(text, font=font)) / 2, y), text,
              font=font, fill=fill)


def caption_png(path, caption, title):
    """Transparent overlay: optional heading up top, caption along the bottom."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if title:
        head, sub = title if isinstance(title, tuple) else (title, None)
        centred(d, head, ImageFont.truetype(find_font("title"), 46), 46, INK)
        if sub:
            # Naming the two halves once, on the opening shot, is enough: a
            # viewer who has never seen a racing sim cannot otherwise tell
            # which half is the game and which half is the thing being shown.
            centred(d, sub, ImageFont.truetype(find_font("mono"), 26), 104, MUTED)

    lines = [caption] if isinstance(caption, str) else list(caption)
    font = ImageFont.truetype(find_font("mono"), 30)
    step = 42
    widest = max(d.textlength(line, font=font) for line in lines)
    top = H - 132 - step * (len(lines) - 1)

    # A plate behind the caption keeps it readable over whatever is behind it.
    d.rounded_rectangle([(W - widest) / 2 - 26, top - 16,
                        (W + widest) / 2 + 26, top + step * (len(lines) - 1) + 48],
                        radius=8, fill=PLATE)
    for i, line in enumerate(lines):
        centred(d, line, font, top + i * step, INK)
    img.save(path)


def end_card_png(path):
    img = Image.new("RGB", (W, H), (8, 11, 13))
    d = ImageDraw.Draw(img)
    for kind, size, text, colour, y in END_CARD:
        centred(d, text, ImageFont.truetype(find_font(kind), size), y, colour)
    img.save(path)


def run(ff, args):
    result = subprocess.run([ff, "-y", *args], capture_output=True, text=True,
                            errors="replace")
    if result.returncode != 0:
        sys.exit(result.stderr[-2000:])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--track", required=True, help="display beside the simulator")
    p.add_argument("--bench", required=True, help="display alone, loss injected")
    p.add_argument("-o", "--output", default="reel.mp4")
    p.add_argument("--work", default="reel-parts", help="scratch directory")
    args = p.parse_args()

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    sources = {"track": args.track, "bench": args.bench}
    os.makedirs(args.work, exist_ok=True)
    parts = []

    for i, (which, start, dur, caption, title, pre) in enumerate(EDIT):
        png = os.path.join(args.work, f"caption{i}.png")
        out = os.path.join(args.work, f"shot{i}.mp4")
        caption_png(png, caption, title)

        # Captions fade so a cut never snaps text on or off; shots fade so the
        # joins read as edits rather than as glitches.
        pre_chain = f"[0:v]{pre}[base];" if pre else ""
        base = "[base]" if pre else "[0:v]"
        chain = (
            f"{pre_chain}"
            f"[1:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1,"
            f"fade=t=out:st={dur - 0.45:.2f}:d=0.35:alpha=1[cap];"
            f"{base}[cap]overlay=0:0:format=auto,"
            f"fade=t=in:st=0:d=0.2,fade=t=out:st={dur - 0.25:.2f}:d=0.25[v];"
            # Short audio fades: cutting a running engine at full level clicks.
            f"[0:a]afade=t=in:st=0:d=0.15,"
            f"afade=t=out:st={dur - 0.25:.2f}:d=0.25[a]"
        )
        # The caption is a looped still, so it never ends on its own. Without
        # a duration on the OUTPUT too, ffmpeg keeps generating frames forever
        # and the shot grows without bound.
        run(ff, ["-ss", str(start), "-t", str(dur), "-i", sources[which],
                 "-loop", "1", "-i", png,
                 "-filter_complex", chain, "-map", "[v]", "-map", "[a]",
                 "-t", str(dur), "-r", str(FPS),
                 "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", out])
        parts.append(out)
        first = caption if isinstance(caption, str) else caption[0]
        print(f"  shot {i}  {dur:4.1f}s  {first}")

    card_png = os.path.join(args.work, "endcard.png")
    card_mp4 = os.path.join(args.work, "endcard.mp4")
    end_card_png(card_png)
    run(ff, ["-loop", "1", "-t", str(END_CARD_SECONDS), "-i", card_png,
             "-f", "lavfi", "-t", str(END_CARD_SECONDS),
             "-i", "anullsrc=r=48000:cl=stereo",
             "-vf", "fade=t=in:st=0:d=0.4,format=yuv420p",
             "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
             "-shortest", card_mp4])
    parts.append(card_mp4)
    print(f"  end card {END_CARD_SECONDS:4.1f}s")

    listing = os.path.join(args.work, "parts.txt")
    with open(listing, "w", encoding="utf-8") as f:
        for part in parts:
            f.write(f"file '{os.path.abspath(part)}'\n")

    # Every part was encoded with identical settings, so the join is a stream
    # copy: no second generation of compression over the whole reel.
    run(ff, ["-f", "concat", "-safe", "0", "-i", listing,
             "-c", "copy", "-movflags", "+faststart", args.output])

    total = sum(shot[2] for shot in EDIT) + END_CARD_SECONDS
    print(f"\n{args.output}  ({total:.1f}s)")


if __name__ == "__main__":
    main()
