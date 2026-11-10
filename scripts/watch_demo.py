"""Exercise a live watcher with a delayed download, then undo its batches."""

import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path


def render_gif(scenes: list[list[str]], output: Path) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise SystemExit("GIF export requires Pillow: python -m pip install Pillow") from exc
    font_path = Path("C:/Windows/Fonts/consola.ttf")
    font = (
        ImageFont.truetype(str(font_path), 19) if font_path.exists() else ImageFont.load_default(19)
    )
    frames = []
    for scene in scenes:
        frame = Image.new("RGB", (1000, 420), "#151719")
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 0, 1000, 46), fill="#25282b")
        draw.text((26, 11), "FilePilot | folder watching", font=font, fill="#eeeeee")
        row = 72
        for line in scene:
            for wrapped in textwrap.wrap(line, width=80) or [""]:
                color = "#97d5a4" if wrapped.startswith(("moved:", "Restored:")) else "#dddddd"
                draw.text((26, row), wrapped, font=font, fill=color)
                row += 28
        frames.append(frame)
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=1600, loop=0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gif", type=Path, help="Export the checked demo scenes as an animated GIF."
    )
    args = parser.parse_args()
    demo_root = Path(__file__).resolve().parents[1] / ".demo"
    demo_root.mkdir(exist_ok=True)
    command = "$ filepilot watch inbox --apply --interval 0.05 --settle 0.15 --max-cycles 20"
    scenes = [[command, "", "Watching inbox (apply). Waiting for files..."]]
    with tempfile.TemporaryDirectory(prefix="watch-", dir=demo_root) as directory:
        root = Path(directory)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "filepilot",
                "watch",
                str(root),
                "--apply",
                "--json",
                "--interval",
                ".05",
                "--settle",
                ".15",
                "--max-cycles",
                "20",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            first = process.stdout.readline()
            assert first and json.loads(first)["event"] == "started", "Watcher failed to start"
            partial = root / "download.pdf.part"
            partial.write_bytes(b"download ")
            time.sleep(0.1)
            assert not (root / "Documents").exists(), "Incomplete download was moved"
            scenes.append([command, "", "download.pdf.part  [writing]", "No files moved."])
            with partial.open("ab") as stream:
                stream.write(b"finished")
            partial.rename(root / "download.pdf")
            (root / "photo.png").write_bytes(b"demo picture")
            scenes.append(
                [
                    command,
                    "",
                    "download.pdf and photo.png arrived.",
                    "Waiting for unchanged metadata...",
                ]
            )
            output, errors = process.communicate(timeout=15)
            assert process.returncode == 0, errors
            events = [json.loads(line) for line in (first + output).splitlines()]
            runs = [event["run"] for event in events if event["event"] == "run"]
            entries = [entry for run in runs for entry in run["entries"]]
            assert len(entries) == 2 and all(entry["status"] == "moved" for entry in entries)
            assert events[-1]["event"] == "stopped" and events[-1]["moved"] == 2
            moved = [f"moved: {entry['source']} -> {entry['target']}" for entry in entries]
            scenes.append([command, "", *moved, "Stopped after 20 polls."])
            for line in moved:
                print(line)
            for run in reversed(runs):
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "filepilot",
                        "undo",
                        str(root),
                        "--run",
                        run["id"],
                        "--apply",
                    ],
                    check=True,
                    capture_output=True,
                )
            assert (root / "download.pdf").read_bytes() == b"download finished"
            assert (root / "photo.png").read_bytes() == b"demo picture"
            scenes.append(
                [
                    "$ filepilot undo inbox --run <batch-id> --apply",
                    "Undo each recorded batch after the watcher stops.",
                    "",
                    "Restored: download.pdf",
                    "Restored: photo.png",
                    "Original bytes verified.",
                ]
            )
            print(
                "Watch demo passed: delayed files moved once; undo restored their original bytes."
            )
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
    if args.gif:
        render_gif(scenes, args.gif)
        print(f"Saved {args.gif}")


if __name__ == "__main__":
    main()
