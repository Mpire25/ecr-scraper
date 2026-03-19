#!/usr/bin/env python3
"""
Fix folder names that were accidentally created with '/' in them.

When a model name like "type 13 / 15 / 17 / 22 / 23" was used as a folder name,
each ' / ' became a directory separator, creating deeply nested folders.
This script finds those nested structures and moves all images up into a
correctly-named flat folder.

Usage:
  python fix_slash_dirs.py /mnt/carvis-data/data
  python fix_slash_dirs.py /mnt/carvis-data/data --dry-run
"""

import argparse
import shutil
from pathlib import Path


SKIP_DIRS = {"train", "val", "test"}


def find_broken_dirs(root: Path):
    """
    Find top-level class dirs that contain only subdirectories (no images directly),
    which indicates the slash-nesting problem.
    """
    broken = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if d.name in SKIP_DIRS:
            continue
        direct_images = list(d.glob("*.jpg"))
        subdirs = [x for x in d.iterdir() if x.is_dir()]
        if not direct_images and subdirs:
            broken.append(d)
    return broken


def collect_images(directory: Path):
    """Recursively collect all .jpg files under a directory."""
    return list(directory.rglob("*.jpg"))


def flatten_dir(broken_dir: Path, dry_run: bool):
    """
    Reconstruct the correct folder name from the nested path structure,
    then move all images into it.
    """
    # The broken dir name is like "bugatti_type 13 " (trailing space)
    # and contains nested subdirs " 15 " / " 17 " / " 22 " / " 23"
    # We need to collect all path segment names and join them with " - "

    images = collect_images(broken_dir)
    if not images:
        print(f"[skip] {broken_dir.name!r} — no images found inside")
        return

    # Build the correct name by walking the nesting
    # Start from broken_dir, descend while there are only subdirs
    segments = [broken_dir.name.strip()]
    current = broken_dir
    while True:
        children = list(current.iterdir())
        subdirs = [c for c in children if c.is_dir()]
        files = [c for c in children if c.is_file()]
        if files or not subdirs:
            break
        if len(subdirs) == 1:
            segments.append(subdirs[0].name.strip())
            current = subdirs[0]
        else:
            # Multiple subdirs — just collect all images recursively from here
            break

    # Re-join the slash-separated parts with " - "
    # segments[0] is like "bugatti_type 13", rest are the sub-parts
    base = segments[0]
    if len(segments) > 1:
        # The original model name was "type 13 / 15 / 17 / 22 / 23"
        # segments[0] = "bugatti_type 13", segments[1] = "15", segments[2] = "17" etc.
        # Split base into make_prefix + first_segment
        first_slash_parts = " - ".join(s.strip() for s in segments[1:])
        correct_name = f"{base} - {first_slash_parts}"
    else:
        correct_name = base

    # Replace any remaining slashes just in case
    correct_name = correct_name.replace("/", "-").replace("\\", "-").strip()

    target_dir = broken_dir.parent / correct_name

    print(f"\n[fix] {broken_dir.name!r}")
    print(f"      -> {correct_name!r}")
    print(f"      {len(images)} images to move")

    if dry_run:
        print("      [dry-run] skipping")
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    for img in images:
        dest = target_dir / img.name
        if dest.exists():
            print(f"      [skip] {img.name} already exists in target")
        else:
            shutil.move(str(img), str(dest))

    # Remove the now-empty broken directory tree
    shutil.rmtree(broken_dir)
    print(f"      [done] removed old nested dir")


def main():
    parser = argparse.ArgumentParser(description="Fix slash-nested car image folders")
    parser.add_argument("data_dir", help="Path to data directory (e.g. /mnt/carvis-data/data)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    args = parser.parse_args()

    root = Path(args.data_dir)
    if not root.is_dir():
        print(f"Error: {root} is not a directory")
        return

    broken = find_broken_dirs(root)
    if not broken:
        print("No broken directories found.")
        return

    print(f"Found {len(broken)} potentially broken director{'y' if len(broken) == 1 else 'ies'}:")
    for d in broken:
        print(f"  {d.name!r}")

    for d in broken:
        flatten_dir(d, dry_run=args.dry_run)

    if args.dry_run:
        print("\n[dry-run complete] No changes made. Re-run without --dry-run to apply.")
    else:
        print("\n[done] All broken directories fixed.")


if __name__ == "__main__":
    main()
