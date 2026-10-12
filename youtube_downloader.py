#!/usr/bin/env python3
"""Download YouTube videos or playlists as MP3 or MP4."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yt_dlp

PROJECT_ROOT = Path(__file__).resolve().parent
DOWNLOAD_DIR = PROJECT_ROOT / "downloads"

QUALITY_MAP = {
    "144p": "bv*[height<=144]+ba/b",
    "240p": "bv*[height<=240]+ba/b",
    "360p": "bv*[height<=360]+ba/b",
    "480p": "bv*[height<=480]+ba/b",
    "720p": "bv*[height<=720]+ba/b",
    "1080p": "bv*[height<=1080]+ba/b",
    "best": "bv*+ba/b",
    "worst": "b/bv",
}


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is required for MP3 conversion and MP4 merging. "
            "Install it with: brew install ffmpeg"
        )


def build_mp4_options(
    output_dir: Path,
    quality: str,
    playlist: bool = False,
    max_items: int | None = None,
    cookies_browser: str | None = None,
) -> dict:
    quality_key = quality.lower()
    format_string = QUALITY_MAP.get(quality_key, QUALITY_MAP["best"])

    outtmpl = (
        str(output_dir / "%(playlist_title,playlist|Playlist)s" / "%(playlist_index&{:02d} - |)s%(title)s.%(ext)s")
        if playlist
        else str(output_dir / "%(title)s.%(ext)s")
    )

    options = {
        "format": format_string,
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "noplaylist": not playlist,
        "ignoreerrors": True,
        "postprocessors": [],
        "restrictfilenames": False,
    }
    if max_items:
        options["max_downloads"] = max_items
    if cookies_browser:
        options["cookiesfrombrowser"] = (cookies_browser, None, None, None)
    return options


def build_mp3_options(
    output_dir: Path,
    playlist: bool = False,
    max_items: int | None = None,
    cookies_browser: str | None = None,
) -> dict:
    outtmpl = (
        str(output_dir / "%(playlist_title,playlist|Playlist)s" / "%(playlist_index&{:02d} - |)s%(title)s.%(ext)s")
        if playlist
        else str(output_dir / "%(title)s.%(ext)s")
    )

    options = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": not playlist,
        "ignoreerrors": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        ],
        "restrictfilenames": False,
    }
    if max_items:
        options["max_downloads"] = max_items
    if cookies_browser:
        options["cookiesfrombrowser"] = (cookies_browser, None, None, None)
    return options


def download_media(
    url: str,
    media_type: str,
    quality: str,
    playlist: bool,
    max_items: int | None = None,
    cookies_browser: str | None = None,
) -> None:
    save_dir = DOWNLOAD_DIR / media_type
    save_dir.mkdir(parents=True, exist_ok=True)

    if media_type == "mp3":
        ensure_ffmpeg()
        options = build_mp3_options(save_dir, playlist=playlist, max_items=max_items, cookies_browser=cookies_browser)
    elif media_type == "mp4":
        ensure_ffmpeg()
        options = build_mp4_options(save_dir, quality, playlist=playlist, max_items=max_items, cookies_browser=cookies_browser)
    else:
        raise ValueError(f"Unsupported type: {media_type}")

    mode_label = "Playlist" if playlist else "Single Video"
    print(f"\n========================================================")
    print(f" Mode:       {mode_label}")
    print(f" Format:     {media_type.upper()}")
    if media_type == "mp4":
        print(f" Quality:    {quality}")
    if max_items:
        print(f" Max items:  {max_items}")
    if cookies_browser:
        print(f" Cookies:    {cookies_browser}")
    print(f" Save dir:   {save_dir}")
    print(f" URL:        {url}")
    print(f"========================================================\n")

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])

    print("\nDownload finished successfully.")


def search_youtube(query: str, limit: int = 15) -> list[dict[str, str]]:
    """Search YouTube and return metadata for the top matching videos."""
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        entries = res.get("entries", []) if res else []
        results = []
        for e in entries:
            if not e or not isinstance(e, dict):
                continue
            dur = e.get("duration")
            dur_str = "N/A"
            if isinstance(dur, (int, float)):
                dur_str = f"{int(dur // 60)}:{int(dur % 60):02d}"
            elif isinstance(dur, str) and dur:
                dur_str = dur

            video_id = e.get("id", "")
            url = e.get("url")
            if not url or not url.startswith("http"):
                if video_id:
                    url = f"https://www.youtube.com/watch?v={video_id}"
                else:
                    continue
            results.append({
                "id": video_id,
                "title": e.get("title", "Unknown Title"),
                "uploader": e.get("uploader") or e.get("channel") or "Unknown",
                "duration": dur_str,
                "url": url,
            })
        return results


def interactive_search(initial_query: str = "", limit: int = 15) -> str | None:
    """Perform YouTube search, display top 15 results, allow search-again, and return selected URL."""
    current_query = initial_query.strip() if initial_query else ""

    while True:
        if not current_query:
            try:
                current_query = input("\nEnter YouTube search query (or 'q' to cancel): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return None
            if not current_query or current_query.lower() in {"q", "quit", "cancel"}:
                return None

        print(f"\n[*] Searching YouTube for: '{current_query}' (showing top {limit} results)...")
        try:
            results = search_youtube(current_query, limit=limit)
        except Exception as err:
            print(f"[!] Error during search: {err}")
            current_query = ""
            continue

        if not results:
            print(f"[!] No results found for query: '{current_query}'")
            current_query = ""
            continue

        print("\n" + "=" * 76)
        print(f" YouTube Search Results for: '{current_query}'")
        print("=" * 76)
        for idx, r in enumerate(results, 1):
            print(f" [{idx:2d}] [{r['duration']:>6s}] {r['title']}")
            print(f"      Channel: {r['uploader']}")
        print("=" * 76)
        print(" Options:")
        print(f"   • Enter a number [1-{len(results)}] to download (Default: 1)")
        print("   • Enter 's' to search again with a new query")
        print("   • Enter 'q' to cancel and go back")

        while True:
            try:
                choice = input(f"\nSelect a video [1-{len(results)}] or action (Default: 1): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return None

            if not choice:
                choice = "1"
            if choice.lower() in {"s", "search", "again"}:
                current_query = ""
                break
            if choice.lower() in {"q", "quit", "cancel", "b", "back"}:
                print("Search cancelled.")
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(results):
                selected = results[int(choice) - 1]
                print(f"\n[✓] Selected: {selected['title']}")
                return selected["url"]
            print(f"[!] Invalid selection. Please enter 1-{len(results)}, 's' to search again, or 'q' to cancel.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download YouTube videos or full playlists as MP4 or MP3, or search YouTube."
    )
    parser.add_argument("url", nargs="?", default=None, help="YouTube video or playlist URL")
    parser.add_argument(
        "--search",
        "-s",
        type=str,
        default=None,
        help="Search query on YouTube to find and download",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Number of search results to display (default: 15)",
    )
    parser.add_argument(
        "--type",
        choices=["mp3", "mp4"],
        default="mp4",
        help="Download format to save (default: mp4)",
    )
    parser.add_argument(
        "--quality",
        choices=["best", "worst", "144p", "240p", "360p", "480p", "720p", "1080p"],
        default="best",
        help="MP4 quality preference (used only for mp4 downloads)",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Download the entire playlist instead of only the first item",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Maximum number of items to download from a playlist (useful for infinite mixes)",
    )
    parser.add_argument(
        "--cookies-from-browser",
        choices=["chrome", "safari", "firefox", "brave", "edge", "opera", "vivaldi"],
        default=None,
        help="Load cookies from your browser to access private or account-specific playlists",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    target_url = args.url

    # If --search query provided without URL, perform interactive search
    if args.search is not None:
        target_url = interactive_search(args.search, limit=args.limit)
        if not target_url:
            sys.exit(0)
    elif not target_url:
        target_url = interactive_search("", limit=args.limit)
        if not target_url:
            sys.exit(0)

    try:
        download_media(
            target_url,
            args.type,
            args.quality,
            args.playlist,
            args.max_items,
            args.cookies_from_browser,
        )
    except Exception as exc:
        raise SystemExit(f"Download failed: {exc}")


if __name__ == "__main__":
    main()
