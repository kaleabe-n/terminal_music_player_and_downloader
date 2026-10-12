# All-in-One Media Downloader & Library Manager

Download videos and audio from **YouTube** and **Spotify** (including full playlists and mixes), and easily clean track filenames and remove duplicate files.

---

## Quick Start (Single Launcher)

Everything is controlled from one single bash file:

```bash
./start.sh
```

When run, you get an interactive menu:

```text
========================================================
        All-in-One Media Downloader & Library Manager   
========================================================

What would you like to do?

  1) Search YouTube & Download (Top 15 Results) [Default]
  2) Download from URL (YouTube or Spotify)
  3) Play Downloaded Music (with Shuffle Option)
  4) Clean Filenames & Remove Duplicates
  5) Exit
```

---

## Features

### 1. Search YouTube & Download (Top 15 Results)
- **Top 15 Results**: Quickly search YouTube directly and see the first 15 results with index, duration, title, and channel name.
- **Search Again Option**: Press `s` at the selection prompt to search for something else without restarting.
- **Instant Download**: Pick a video number (1-15) and download directly as MP3 or MP4 (with quality selection).

### 2. Download from URL (YouTube & Spotify)
- **Universal Input**: Paste any **YouTube** (video, playlist, mix) or **Spotify** (playlist, album, track) link.
- **YouTube**:
  - Download as **MP3** (audio) or **MP4** (video with quality up to 1080p/best).
  - Automatically detects playlists & mixes with full download progress.
  - Supports private playlists via browser cookies (`--cookies-from-browser`).
- **Spotify**:
  - Downloads full playlists and albums with official **album cover artwork**, track titles, artists, and metadata embedded into ID3 tags.
  - Supports MP3 (up to 320 kbps), M4A, FLAC.
  - Multi-source audio matching (YouTube Music, YouTube, SoundCloud).

### 3. Terminal Media Player (with Background Playback, Seeking, Beats & OS Keys)
- **Built-in Player**: Play downloaded music and videos natively via macOS `ffplay` or `afplay`.
- **Background Playback & Return**: Press **`b`** or **`m`** to return to the main menu while audio keeps playing in the background. On the main menu, the player option dynamically updates to **`Back to Player (▶ Playing: Track Title)`** and re-attaches instantly without restarting.
- **Seeking Controls**: Jump forward by 5s (**`5`** or **`]`**), forward by 10s (**`0`** or **`}`**), or rewind 5s (**`,`** or **`[`**).
- **Queue Browser with 'Next' Pages**: Press **`l`** to view upcoming tracks paginated (10 per page); press **`n`** to see more coming soon tracks, **`p`** for previous, or a track number to jump.
- **Moving Beats Visualizer**: Rhythmic animated equalizer dots (`⡀ ⡄ ⡆ ⡇ ⣇ ⣧ ⣷ ⣿`) bounce and pulse to audio beats with zero terminal flicker.
- **macOS Media Keys & AirPods**: Listens to system hardware media buttons (**Play/Pause**, **Next**, **Previous**, F7/F8/F9, Touch Bar, Control Center, and Bluetooth headphones / AirPods).
- **In-Player Search**: Press **`/`** or **`f`** to search and jump to any track by name or folder.
- **Likes & Favorites**: Press **`k`** to like/favorite a song (persisted to `.favorites.txt`); filter by favorites on startup.
- **Interactive Hotkeys**:
  - `[Space]` Pause / Resume
  - `[n]` or `[→]` Next track
  - `[p]` or `[←]` Previous track
  - `[5]` / `[0]` Seek +5s / +10s (rewind with `[,]`)
  - `[b]` or `[m]` Back to Main Menu (Keep Playing in Background)
  - `[q]` Stop Player & Exit
  - `[/]` or `[f]` Search library & jump
  - `[k]` Like / Favorite song (❤️)
  - `[s]` Toggle Shuffle mode (On / Off)
  - `[t]` Toggle Repeat mode (ALL / ONE / OFF)
  - `[r]` Replay current track from start
  - `[l]` List upcoming queue with pagination (Next / Prev)

### 4. Clean Filenames & Remove Duplicates
- **Strip Track Number Prefixes**: Cleans prefixes like `01 - `, `78 - `, `04. ` from filenames.
- **Duplicate Detection**: Finds duplicate songs across different playlists using MD5 audio hash verification and normalized title matching.
- **Safe Mode**: Moves duplicates to `.duplicates_trash` by default so no files are accidentally lost.
- **Dry Run**: Simulates and previews changes before applying them.

---

## Direct CLI Usage

You can also pass arguments directly to `./start.sh` without the interactive menu:

```bash
# Play all downloaded tracks in Shuffle mode
./start.sh --play --shuffle

# Play specific folder
./start.sh --play downloads/mp3

# Search YouTube directly and download
./start.sh --search "lofi hip hop" --type mp3

# Download a YouTube video / playlist
./start.sh "https://www.youtube.com/watch?v=VIDEO_ID" --type mp3

# Download a Spotify playlist
./start.sh "https://open.spotify.com/playlist/PLAYLIST_ID" --format mp3 --bitrate 320k

# Run library cleanup directly (dry run)
./start.sh --clean --dry-run
```

---

## Requirements

- macOS / Linux
- Python 3.10+
- `ffmpeg` (installed via `brew install ffmpeg`)
# terminal_music_player_and_downloader
