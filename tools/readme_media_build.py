"""Builds the README media from a showcase capture: screenshots, the 3D flow as GIF and MP4, the turntable.

Usage: python3 tools/readme_media_build.py <capture folder> <docs/media>
Needs ffmpeg. Waits for Scenario are sped up; everything else plays at the
speed it was recorded. A contact sheet of every output is written to the
capture folder for review.
"""

import json
import os
import shutil
import subprocess
import sys

SHOTS = (  # the stills the README shows
    "panel_signin",
    "panel_image_ready",
    "image_card",
    "image_material",
    "picker_3d",
    "panel_3d_priced",
    "panel_3d_generating",
    "panel_3d_imported",
    "hero",
)
WAITS = {"image_wait": 0.08, "model_wait": 0.06}  # seconds shown per frame while Scenario works
FLOW_3D = ("model_type", "model_wait", "model_import")
FLOW_CROP = "crop=iw*0.65:ih*0.84:iw*0.35:ih*0.04"  # the viewport's centre and the panel: the rest stays empty
FONTS = ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf")  # montage needs one


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def concat_list(frames, path):
    """An ffmpeg concat list: each frame lasts until the next one, waits compressed, pauses capped."""
    lines = []
    for index, frame in enumerate(frames):
        following = frames[index + 1]["t"] if index + 1 < len(frames) else frame["t"] + 1.5
        duration = WAITS.get(frame["phase"]) or min(max(following - frame["t"], 0.04), 1.5)
        lines += [f"file '{frame['path']}'", f"duration {duration:.3f}"]
    lines.append(f"file '{frames[-1]['path']}'")  # the concat demuxer drops the last duration otherwise
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def gif(source, out, width, fps, crop=""):
    palette = out + ".palette.png"
    scale = (f"{crop}," if crop else "") + f"fps={fps},scale={width}:-1:flags=lanczos"
    run("ffmpeg", "-y", "-loglevel", "error", "-i", source, "-vf", f"{scale},palettegen=stats_mode=diff", palette)
    run("ffmpeg", "-y", "-loglevel", "error", "-i", source, "-i", palette, "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", out)
    os.remove(palette)


def mp4_from_list(listing, out, width):
    run(
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        listing,
        "-vf",
        f"fps=25,scale={width}:-2:flags=lanczos,format=yuv420p",
        "-c:v",
        "libx264",
        "-crf",
        "22",
        "-movflags",
        "+faststart",
        out,
    )


def main(capture, media):
    with open(os.path.join(capture, "showcase.json")) as handle:
        show = json.load(handle)
    os.makedirs(media, exist_ok=True)
    made = []
    for name in SHOTS:
        for ext in (".png", ".jpg"):
            source = os.path.join(capture, "shots", name + ext)
            if os.path.exists(source):
                target = os.path.join(media, name.replace("_", "-") + ext)
                shutil.copyfile(source, target)
                made.append(target)

    frames = [frame for frame in show["frames"] if os.path.exists(frame["path"])]
    flow = [frame for frame in frames if frame["phase"] in FLOW_3D]
    if flow:
        listing = concat_list(flow, os.path.join(capture, "flow_3d.txt"))
        mp4 = os.path.join(media, "flow-3d.mp4")
        mp4_from_list(listing, mp4, 1600)
        gif(mp4, os.path.join(media, "flow-3d.gif"), 900, 10, crop=FLOW_CROP)
        made += [mp4, os.path.join(media, "flow-3d.gif")]
    everything = [frame for frame in frames if frame["phase"] != "turntable"]
    if everything:
        listing = concat_list(everything, os.path.join(capture, "session.txt"))
        mp4 = os.path.join(media, "session.mp4")
        mp4_from_list(listing, mp4, 1600)
        made.append(mp4)

    turn = os.path.join(capture, "turntable")
    if os.path.exists(os.path.join(turn, "t0001.jpg")):
        mp4 = os.path.join(media, "turntable.mp4")
        pattern = os.path.join(turn, "t%04d.jpg")
        run(
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            "24",
            "-i",
            pattern,
            "-vf",
            "scale=1280:-2:flags=lanczos,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            mp4,
        )
        gif(mp4, os.path.join(media, "turntable.gif"), 640, 20)
        made += [mp4, os.path.join(media, "turntable.gif")]

    for path in made:
        print(f"   {os.path.getsize(path) / 1e6:6.2f} MB  {os.path.relpath(path, os.path.dirname(media))}")
    stills = [path for path in made if path.endswith((".png", ".jpg"))]
    fonts = [path for path in FONTS if os.path.exists(path)]
    if stills and fonts and shutil.which("magick"):
        sheet = os.path.join(capture, "contact_sheet.jpg")
        subprocess.run(["magick", "montage", "-font", fonts[0], *stills, "-geometry", "520x340+6+6", "-tile", "4x", sheet], check=False)
        print(f"   contact sheet: {sheet}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
