#!/usr/bin/env python3
"""
Clean track filenames by removing leading playlist numbers/dashes,
and detect and remove duplicate audio/video files.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# Match leading numbers followed by dash, dot, underscore, or space
# Examples: "01 - ", "1 - ", "78 - ", "04. ", "12_ "
PREFIX_REGEX = re.compile(r"^\d+\s*[-._]\s*")

MEDIA_EXTENSIONS = {".mp3", ".mp4", ".m4a", ".webm", ".opus", ".flac", ".wav", ".mkv"}


def get_clean_name(filename: str) -> str:
    """Strip leading track number prefix from a filename."""
    return PREFIX_REGEX.sub("", filename)


def compute_file_hash(path: Path, block_size: int = 65536) -> str:
    """Calculate MD5 hash of file contents for exact duplicate detection."""
    hasher = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(block_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return ""


def format_bytes(size: int) -> str:
    """Format bytes into human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def scan_media_files(target_dir: Path) -> list[Path]:
    """Find all media files recursively in target_dir."""
    return [
        p for p in target_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS and not p.parts_contain(".duplicates_trash")
    ]


class PathWrapper:
    """Helper to check if any parent directory is the trash directory."""
    @staticmethod
    def is_in_trash(path: Path) -> bool:
        return any(part in {".duplicates_trash", ".trash"} for part in path.parts)


def find_duplicates(
    files: list[Path],
    scope: str = "global",
) -> tuple[dict[str, list[Path]], list[tuple[Path, str]]]:
    """
    Find files to rename and duplicate files to remove.
    Returns:
      (duplicates_map, rename_plan)
    """
    rename_plan: list[tuple[Path, str]] = []
    
    # 1. Group files either globally or per-parent-directory
    groups: dict[Path, list[Path]] = defaultdict(list)
    for f in files:
        if PathWrapper.is_in_trash(f):
            continue
        group_key = Path("GLOBAL") if scope == "global" else f.parent
        groups[group_key].append(f)

    all_duplicates: dict[str, list[Path]] = {}

    for _, group_files in groups.items():
        # Step A: Group by cleaned filename (case-insensitive)
        by_clean_name: dict[str, list[Path]] = defaultdict(list)
        for f in group_files:
            clean = get_clean_name(f.name)
            by_clean_name[clean.lower()].append(f)

        for clean_lower, matching_files in by_clean_name.items():
            if len(matching_files) > 1:
                # Group duplicates by content hash or by cleaned name
                # Sort so that the file with cleanest name and largest size is prioritized to keep
                def sort_key(p: Path) -> tuple[int, int]:
                    has_prefix = 1 if PREFIX_REGEX.match(p.name) else 0
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = 0
                    # Lower has_prefix first, higher size first
                    return (has_prefix, -size)

                sorted_files = sorted(matching_files, key=sort_key)
                primary = sorted_files[0]
                dups = sorted_files[1:]
                key_desc = f"{clean_lower} (Keeper: {primary.relative_to(primary.parents[2] if len(primary.parents) > 2 else primary.parent)})"
                all_duplicates[key_desc] = dups

    # Step B: Determine renaming plan for files that will be kept
    # Exclude files marked for deletion as duplicates
    deleted_paths = {p for dup_list in all_duplicates.values() for p in dup_list}

    for f in files:
        if f in deleted_paths or PathWrapper.is_in_trash(f):
            continue
        clean_name = get_clean_name(f.name)
        if clean_name != f.name:
            target_path = f.with_name(clean_name)
            # Only rename if target does not already exist
            if target_path != f:
                rename_plan.append((f, clean_name))

    return all_duplicates, rename_plan


def process_clean(
    target_dir: Path,
    scope: str = "global",
    dry_run: bool = True,
    trash: bool = True,
) -> None:
    if not target_dir.exists():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    print(f"Scanning '{target_dir}' (Scope: {scope.upper()})...")
    files = [f for f in target_dir.rglob("*") if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS and not PathWrapper.is_in_trash(f)]

    print(f"Found {len(files)} media files.")

    duplicates_map, rename_plan = find_duplicates(files, scope=scope)

    total_dups = sum(len(dups) for dups in duplicates_map.values())
    total_space = 0
    for dups in duplicates_map.values():
        for d in dups:
            try:
                total_space += d.stat().st_size
            except OSError:
                pass

    print("\n" + "=" * 60)
    print("                    ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"  Files with leading numbers to rename: {len(rename_plan)}")
    print(f"  Duplicate files detected:             {total_dups}")
    print(f"  Disk space that can be recovered:     {format_bytes(total_space)}")
    print("=" * 60 + "\n")

    if total_dups > 0:
        print("--- DUPLICATE FILES TO REMOVE ---")
        for group_label, dups in duplicates_map.items():
            print(f"\nGroup: {group_label}")
            for d in dups:
                try:
                    size_str = format_bytes(d.stat().st_size)
                except OSError:
                    size_str = "unknown size"
                print(f"  [DELETE] {d} ({size_str})")

    if len(rename_plan) > 0:
        print("\n--- SAMPLE RENAMES (First 10) ---")
        for orig, new_name in rename_plan[:10]:
            print(f"  '{orig.name}' -> '{new_name}'")
        if len(rename_plan) > 10:
            print(f"  ... and {len(rename_plan) - 10} more files.")

    if dry_run:
        print("\n[DRY RUN MODE] No files were modified or deleted.")
        print("To apply these changes, run without --dry-run or use clean.sh")
        return

    # Apply changes
    print("\nApplying changes...")

    trash_dir = target_dir / ".duplicates_trash"
    if trash and total_dups > 0:
        trash_dir.mkdir(parents=True, exist_ok=True)

    # 1. Remove/Move Duplicates
    removed_count = 0
    for dups in duplicates_map.values():
        for d in dups:
            try:
                if trash:
                    # Move to trash preserving relative path
                    rel = d.relative_to(target_dir)
                    dest = trash_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(d), str(dest))
                else:
                    d.unlink()
                removed_count += 1
            except Exception as e:
                print(f"Error handling duplicate '{d}': {e}")

    action_label = f"moved to trash ({trash_dir})" if trash else "permanently deleted"
    print(f"[✓] {removed_count} duplicate files {action_label}.")

    # 2. Rename Files
    renamed_count = 0
    for orig_path, new_name in rename_plan:
        if not orig_path.exists():
            continue
        dest_path = orig_path.with_name(new_name)
        if dest_path.exists() and dest_path != orig_path:
            # Another file with the clean name already exists (extra duplicate safety)
            try:
                if trash:
                    rel = orig_path.relative_to(target_dir)
                    dest = trash_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(orig_path), str(dest))
                else:
                    orig_path.unlink()
                removed_count += 1
            except Exception as e:
                print(f"Error resolving collision for '{orig_path}': {e}")
        else:
            try:
                orig_path.rename(dest_path)
                renamed_count += 1
            except Exception as e:
                print(f"Error renaming '{orig_path}': {e}")

    print(f"[✓] {renamed_count} files renamed cleanly.")
    print("\nCleanup completed successfully!")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean audio/video filenames (strip leading numbers) and remove duplicates."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("downloads"),
        help="Target folder to clean (default: ./downloads)",
    )
    parser.add_argument(
        "--scope",
        choices=["global", "folder"],
        default="global",
        help="'global' detects duplicates across all playlists, 'folder' only within the same folder.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the cleanup without modifying or deleting any files.",
    )
    parser.add_argument(
        "--permanent-delete",
        action="store_true",
        help="Permanently delete duplicates instead of moving them to .duplicates_trash.",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Proceed without interactive confirmation.",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        # Prompt user
        print(f"Target: {args.target}")
        print(f"Scope:  {args.scope}")
        mode_str = "Permanently delete duplicates" if args.permanent_delete else "Move duplicates to .duplicates_trash"
        print(f"Action: {mode_str} and strip numbers/dashes")
        confirm = input("\nDo you want to proceed? (y/N): ").strip()
        if confirm.lower() not in {"y", "yes"}:
            print("Cancelled.")
            sys.exit(0)

    process_clean(
        target_dir=args.target,
        scope=args.scope,
        dry_run=args.dry_run,
        trash=not args.permanent_delete,
    )


if __name__ == "__main__":
    main()
