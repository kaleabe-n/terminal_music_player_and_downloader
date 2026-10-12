#!/usr/bin/env python3
"""
Spotify Playlist, Album, and Track Downloader.
Extracts tracks from Spotify and downloads high-quality audio using yt-dlp and ffmpeg.
Works out-of-the-box without requiring Spotify API keys or developer accounts.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yt_dlp

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DOWNLOAD_DIR = PROJECT_ROOT / "downloads" / "spotify"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is required for audio conversion. "
            "Install it on macOS with: brew install ffmpeg"
        )


def sanitize_filename(name: str) -> str:
    """Strip characters that are invalid in file and folder names."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def parse_spotify_url(url: str) -> tuple[str, str]:
    """
    Extract the Spotify entity type ('playlist', 'album', 'track') and ID.
    Supports standard open.spotify.com and spotify.link URLs.
    """
    # Follow redirects for shortlinks like spotify.link
    if "spotify.link" in url:
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                url = resp.geturl()
        except Exception:
            pass

    match = re.search(r"spotify\.com/(?:intl-[a-z]+/)?(playlist|album|track)/([a-zA-Z0-9]+)", url)
    if not match:
        raise ValueError(f"Could not recognize a valid Spotify URL: {url}")
    return match.group(1), match.group(2)


def fetch_spotify_metadata(entity_type: str, entity_id: str) -> dict[str, Any]:
    """
    Fetch playlist, album, or track metadata directly from Spotify's embed endpoint.
    Requires no developer account or API credentials.
    """
    embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
    req = urllib.request.Request(embed_url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to connect to Spotify: {exc}")

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
    if not match:
        raise RuntimeError("Unable to extract playlist data from Spotify embed page.")

    try:
        data = json.loads(match.group(1))
        page_props = data.get("props", {}).get("pageProps", {})
        entity = page_props.get("state", {}).get("data", {}).get("entity", {})
        if not entity:
            raise ValueError("Spotify returned empty entity data.")
        return entity
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Error parsing Spotify response: {exc}")


def extract_tracks(entity_type: str, entity: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """
    Extract container title and track items (title, artist, search_query).
    """
    tracks: list[dict[str, str]] = []

    if entity_type == "track":
        title = entity.get("title") or entity.get("name") or "Unknown Title"
        artists_data = entity.get("artists", [])
        if isinstance(artists_data, list) and artists_data:
            artist = ", ".join(a.get("name", "") for a in artists_data if isinstance(a, dict))
        else:
            artist = entity.get("subtitle", "Unknown Artist")
        tracks.append({
            "title": title.strip(),
            "artist": artist.strip(),
            "query": f"{artist.strip()} - {title.strip()}",
        })
        container_title = ""
    else:
        container_title = entity.get("title") or entity.get("name") or "Spotify Playlist"
        track_list = entity.get("trackList", [])
        for item in track_list:
            t_title = (item.get("title") or "").strip()
            t_artist = (item.get("subtitle") or "").strip()
            if t_title:
                tracks.append({
                    "title": t_title,
                    "artist": t_artist,
                    "query": f"{t_artist} - {t_title}" if t_artist else t_title,
                })

    return sanitize_filename(container_title), tracks


def download_track(
    track_info: dict[str, str],
    target_dir: Path,
    audio_format: str = "mp3",
    bitrate: str = "320k",
) -> bool:
    """Download a single track using yt-dlp searching YouTube audio."""
    query = track_info["query"]
    safe_filename = sanitize_filename(f"{track_info['artist']} - {track_info['title']}" if track_info['artist'] else track_info['title'])
    target_path = target_dir / f"{safe_filename}.{audio_format}"

    # Skip if file already exists
    if target_path.exists() and target_path.stat().st_size > 10000:
        print(f"[skip] Already exists: {target_path.name}")
        return True

    bitrate_val = "0"
    if bitrate.endswith("k"):
        bitrate_val = bitrate[:-1]

    outtmpl = str(target_dir / f"{safe_filename}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "ignoreerrors": True,
        "quiet": False,
        "no_warnings": True,
        "default_search": "ytsearch1",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": bitrate_val,
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            },
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            exit_code = ydl.download([f"ytsearch1:{query}"])
            return exit_code == 0
    except Exception as exc:
        print(f"[error] Failed to download '{query}': {exc}")
        return False


def download_spotify(
    url: str,
    output_dir: Path = DEFAULT_DOWNLOAD_DIR,
    audio_format: str = "mp3",
    bitrate: str = "320k",
) -> int:
    ensure_ffmpeg()

    print(f"\n[*] Fetching Spotify metadata for: {url}")
    entity_type, entity_id = parse_spotify_url(url)
    entity_data = fetch_spotify_metadata(entity_type, entity_id)
    container_title, tracks = extract_tracks(entity_type, entity_data)

    if not tracks:
        print("[!] No tracks found in the provided Spotify URL.")
        return 1

    # Output directory
    if container_title:
        save_dir = output_dir / container_title
    else:
        save_dir = output_dir

    save_dir.mkdir(parents=True, exist_ok=True)

    print("\n========================================================")
    print(" Spotify Downloader")
    if container_title:
        print(f" Name:       {container_title} ({len(tracks)} tracks)")
    else:
        print(f" Track:      {tracks[0]['query']}")
    print(f" Format:     {audio_format.upper()} ({bitrate})")
    print(f" Save Dir:   {save_dir}")
    print("========================================================\n")

    successful = 0
    for idx, t in enumerate(tracks, 1):
        print(f"\n[{idx}/{len(tracks)}] Processing: {t['query']}")
        ok = download_track(
            track_info=t,
            target_dir=save_dir,
            audio_format=audio_format,
            bitrate=bitrate,
        )
        if ok:
            successful += 1

    print("\n========================================================")
    print(f" [✓] Completed: {successful}/{len(tracks)} tracks downloaded successfully!")
    print(f" Saved to: {save_dir}")
    print("========================================================\n")

    return 0 if successful > 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Spotify playlists, albums, or tracks as MP3/M4A with full metadata."
    )
    parser.add_argument("url", help="Spotify playlist, album, or track URL")
    parser.add_argument(
        "--format",
        choices=["mp3", "m4a", "flac", "opus", "wav"],
        default="mp3",
        help="Audio format to save (default: mp3)",
    )
    parser.add_argument(
        "--bitrate",
        choices=["320k", "256k", "192k", "128k", "auto"],
        default="320k",
        help="Audio bitrate quality (default: 320k)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DOWNLOAD_DIR,
        help="Directory to save downloads",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        code = download_spotify(
            url=args.url,
            output_dir=args.output_dir,
            audio_format=args.format,
            bitrate=args.bitrate,
        )
        sys.exit(code)
    except Exception as exc:
        raise SystemExit(f"Download failed: {exc}")


if __name__ == "__main__":
    main()
