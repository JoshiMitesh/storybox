#!/usr/bin/env python3

import json
import os
import re
import subprocess
import time
from pathlib import Path

STORIES_DIR = Path("/home/admin/stories")
PROMPTS_DIR = Path("/home/admin/story-prompts")
CATALOG = Path("/home/admin/story-library.json")

PIPER = "/opt/piper/piper"
MODEL = "/opt/piper/models/en_US-lessac-medium.onnx"

SUPPORTED = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
POLL_SECONDS = 2
observed = {}

def story_name(filename):
    # Remove extension, hyphens, underscores and other filename symbols.
    name = Path(filename).stem
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"[^A-Za-z0-9 ]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.title()

def prompt_filename(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{slug}.wav"

def generate_prompt(title, destination):
    raw = PROMPTS_DIR / f".{destination.stem}.raw.wav"
    final_tmp = PROMPTS_DIR / f".{destination.stem}.tmp.wav"

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = "/opt/piper"

    try:
        subprocess.run(
            [
                PIPER,
                "--model", MODEL,
                "--output_file", str(raw),
            ],
            input=(title + "\n").encode("utf-8"),
            env=env,
            check=True,
            timeout=120,
        )

        # Add the same 600 ms leading silence used by the existing prompts.
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(raw),
                "-af", "adelay=600:all=1",
                "-ac", "1",
                "-ar", "22050",
                "-c:a", "pcm_s16le",
                str(final_tmp),
            ],
            check=True,
            timeout=120,
        )

        final_tmp.replace(destination)
        print(f"Generated prompt: {title}", flush=True)

    finally:
        raw.unlink(missing_ok=True)
        final_tmp.unlink(missing_ok=True)

def update_catalog():
    entries = []

    for audio in sorted(STORIES_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not audio.is_file() or audio.suffix.lower() not in SUPPORTED:
            continue

        title = story_name(audio.name)
        if not title:
            continue

        prompt = prompt_filename(title)
        prompt_path = PROMPTS_DIR / prompt

        if not prompt_path.is_file():
            continue

        entries.append({
            "title": title,
            "filename": audio.name,
            "prompt": prompt,
        })

    temp = CATALOG.with_suffix(".json.tmp")
    temp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    temp.replace(CATALOG)

    print(f"Catalog updated: {len(entries)} stories", flush=True)

def scan():
    changed = False

    # Read the previous catalog so we can identify deleted stories.
    try:
        old_entries = json.loads(CATALOG.read_text())
        if not isinstance(old_entries, list):
            old_entries = []
    except (OSError, json.JSONDecodeError):
        old_entries = []

    audio_files = sorted(
        [
            p for p in STORIES_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED
        ],
        key=lambda p: p.name.lower(),
    )

    present_filenames = {audio.name for audio in audio_files}
    entries = []

    for audio in audio_files:
        try:
            stat = audio.stat()
        except FileNotFoundError:
            continue

        signature = (stat.st_size, stat.st_mtime_ns)
        previous = observed.get(str(audio))

        if previous and previous[0] == signature:
            stable_count = previous[1] + 1
        else:
            stable_count = 0

        observed[str(audio)] = (signature, stable_count)

        title = story_name(audio.name)
        if not title:
            continue

        prompt = prompt_filename(title)
        prompt_path = PROMPTS_DIR / prompt

        # Wait until a newly copied file has stopped changing.
        if not prompt_path.exists() or prompt_path.stat().st_mtime < stat.st_mtime:
            if stable_count >= 2 and time.time() - stat.st_mtime >= 3:
                try:
                    print(f"Processing story: {audio.name}", flush=True)
                    generate_prompt(title, prompt_path)
                    changed = True
                except Exception as error:
                    print(f"ERROR processing {audio.name}: {error}", flush=True)

        if prompt_path.is_file():
            entries.append({
                "title": title,
                "filename": audio.name,
                "prompt": prompt,
            })

    # Remove prompts belonging only to stories that were deleted.
    active_prompts = {entry["prompt"] for entry in entries}

    for old in old_entries:
        filename = old.get("filename")
        prompt = old.get("prompt")

        if (
            filename
            and filename not in present_filenames
            and prompt
            and prompt not in active_prompts
        ):
            old_prompt = PROMPTS_DIR / Path(prompt).name

            if old_prompt.parent == PROMPTS_DIR and old_prompt.is_file():
                old_prompt.unlink()
                print(f"Removed unused prompt: {old_prompt.name}", flush=True)

    # Remove deleted files from the in-memory stability tracker.
    for tracked in list(observed):
        if Path(tracked).name not in present_filenames:
            observed.pop(tracked, None)

    # Update the catalog only when its contents actually change.
    old_catalog = json.dumps(old_entries, indent=2, ensure_ascii=False)
    new_catalog = json.dumps(entries, indent=2, ensure_ascii=False)

    if old_catalog != new_catalog:
        temp = CATALOG.with_suffix(".json.tmp")
        temp.write_text(new_catalog + "\\n")
        temp.replace(CATALOG)
        print(f"Catalog synchronized: {len(entries)} stories", flush=True)

def main():
    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    print("StoryBox automatic story manager started", flush=True)

    # Process existing files as well as newly added files.
    while True:
        try:
            scan()
        except Exception as error:
            print(f"Watcher error: {error}", flush=True)

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
