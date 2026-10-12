#!/usr/bin/env python3
"""Interactive audio/media player with daemon/background support, seeking, moving beats, search, shuffle, and OS media keys."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import select
import shutil
import signal
import socket
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SOCKET_PATH = PROJECT_ROOT / ".player.sock"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav", ".aac", ".opus", ".ogg", ".mp4"}

BEATS_DOTS = [" ", "⡀", "⡄", "⡆", "⡇", "⣇", "⣧", "⣷", "⣿"]
BEATS_COLORS = [
    "\033[90m",    # 0: gray
    "\033[32m",    # 1: green
    "\033[32m",    # 2: green
    "\033[36m",    # 3: cyan
    "\033[36m",    # 4: cyan
    "\033[33m",    # 5: yellow
    "\033[33m",    # 6: yellow
    "\033[35m",    # 7: magenta
    "\033[1;31m",  # 8: bold red
]

EQUALIZER_COLORS = [
    "\033[1;31m",  # Row 8 (Peak): Red
    "\033[35m",    # Row 7: Magenta
    "\033[1;33m",  # Row 6: Orange/Bright Yellow
    "\033[33m",    # Row 5: Yellow
    "\033[36m",    # Row 4: Cyan
    "\033[1;32m",  # Row 3: Bright Green
    "\033[32m",    # Row 2: Green
    "\033[32m",    # Row 1: Green
]


def generate_equalizer_heights(tick: int, cols: int = 24, max_height: int = 8) -> list[int]:
    """Generate rhythmic audio equalizer heights for bass, mids, and treble."""
    heights = []
    t = tick * 0.45
    for c in range(cols):
        rel_pos = c / cols
        if rel_pos < 0.3:
            pulse = math.sin(t * 1.2) * 0.5 + 0.5
            val = 2.0 + (max_height - 2.5) * (pulse ** 2) * abs(math.cos(c * 0.4))
        elif rel_pos < 0.7:
            pulse = math.sin(t * 0.9 + c * 0.5) * math.cos(t * 0.6 - c * 0.2)
            val = 1.5 + (max_height - 2.0) * abs(pulse)
        else:
            pulse = math.sin(t * 1.5 + c * 0.8) * math.cos(t * 1.1 + c * 0.3)
            val = 1.0 + (max_height - 2.5) * abs(pulse)

        h = int(round(val))
        h = max(1, min(max_height, h))
        heights.append(h)
    return heights



def find_tracks(directory: Path) -> list[Path]:
    """Recursively discover all supported media files in directory, ignoring trash and hidden files."""
    if not directory.exists():
        return []

    tracks: list[Path] = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != ".duplicates_trash"]
        for f in files:
            if f.startswith("."):
                continue
            p = Path(root) / f
            if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                tracks.append(p)

    tracks.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
    return tracks


def load_favorites(favorites_file: Path) -> set[str]:
    """Load set of relative paths of liked/favorite tracks."""
    if not favorites_file.exists():
        return set()
    try:
        lines = favorites_file.read_text(encoding="utf-8").splitlines()
        return {line.strip() for line in lines if line.strip() and not line.startswith("#")}
    except Exception:
        return set()


def save_favorites(favorites_file: Path, favorites: set[str]) -> None:
    """Save set of liked track keys to file."""
    try:
        favorites_file.write_text("\n".join(sorted(favorites)) + "\n", encoding="utf-8")
    except Exception:
        pass


def get_player_command() -> str:
    """Return available CLI player (prefers ffplay for seeking support, falls back to afplay)."""
    if shutil.which("ffplay"):
        return "ffplay"
    if shutil.which("afplay"):
        return "afplay"
    raise RuntimeError("No compatible audio player found. Please install ffmpeg (ffplay) or use macOS afplay.")


def send_daemon_command(cmd: str, timeout: float = 1.0) -> dict | None:
    """Send command to running player daemon over UNIX socket and return parsed response."""
    if not SOCKET_PATH.exists():
        return None

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(SOCKET_PATH))
        sock.sendall((cmd.strip() + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        sock.close()
        if not data:
            return None
        return json.loads(data.decode("utf-8").strip())
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return None


def is_daemon_alive() -> bool:
    """Check if background player daemon is active and responding."""
    res = send_daemon_command("PING", timeout=0.2)
    return bool(res and res.get("status") == "PONG")


class OSMediaKeyBridge:
    """Bridges macOS system media keys (Play/Pause, Next, Prev, AirPods/Headphones) to the player."""

    def __init__(self, on_command_callback) -> None:
        self.on_command = on_command_callback
        self.process: subprocess.Popen | None = None
        self.worker_thread: threading.Thread | None = None
        self.running = False
        self.is_active = False

    def start(self) -> None:
        if sys.platform != "darwin":
            return

        bin_path = PROJECT_ROOT / "media_keys_listener"
        swift_path = PROJECT_ROOT / "media_keys_listener.swift"

        # Compile swift listener if binary is missing
        if not bin_path.exists() and swift_path.exists():
            try:
                subprocess.run(
                    ["swiftc", "-O", str(swift_path), "-o", str(bin_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            except Exception:
                return

        if not bin_path.exists():
            return

        try:
            self.process = subprocess.Popen(
                [str(bin_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            self.running = True
            self.is_active = True
            self.worker_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.worker_thread.start()
        except Exception:
            self.process = None
            self.is_active = False

    def _reader_loop(self) -> None:
        if not self.process or not self.process.stdout:
            return

        for line in self.process.stdout:
            if not self.running:
                break
            cmd = line.strip()
            if cmd in {"TOGGLE_PLAY_PAUSE", "PLAY", "PAUSE", "NEXT", "PREV"}:
                try:
                    self.on_command(cmd)
                except Exception:
                    pass

    def update_now_playing(self, title: str, artist: str = "", is_playing: bool = True) -> None:
        if not self.process or not self.process.stdin or not self.running:
            return
        state_str = "PLAYING" if is_playing else "PAUSED"
        clean_title = title.replace("|", "-")
        clean_artist = artist.replace("|", "-")
        try:
            self.process.stdin.write(f"NOW_PLAYING:{clean_title}|{clean_artist}|{state_str}\n")
            self.process.stdin.flush()
        except Exception:
            pass

    def stop(self) -> None:
        self.running = False
        self.is_active = False
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.write("QUIT\n")
                    self.process.stdin.flush()
                self.process.terminate()
                self.process.wait(timeout=0.3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None


class RawTerminal:
    """Context manager to enable single-character input without pressing Enter."""

    def __init__(self) -> None:
        self.fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        self.old_settings = None

    def enable_cbreak(self) -> None:
        if self.fd is not None:
            try:
                self.old_settings = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
            except Exception:
                pass

    def restore(self) -> None:
        if self.fd is not None and self.old_settings is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass

    def __enter__(self) -> RawTerminal:
        self.enable_cbreak()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.restore()


def read_key_nonblocking(timeout_sec: float = 0.1) -> str | None:
    """Read a single keypress if available within timeout."""
    try:
        rlist, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if not rlist:
            return None

        ch = sys.stdin.read(1)
        if not ch:  # EOF reached
            return "q"

        # Handle escape sequences for arrow keys
        if ch == "\x1b":
            rlist2, _, _ = select.select([sys.stdin], [], [], 0.05)
            if rlist2:
                seq = sys.stdin.read(2)
                if seq == "[C":  # Right arrow
                    return "right"
                elif seq == "[D":  # Left arrow
                    return "left"
                elif seq == "[A":  # Up arrow
                    return "up"
                elif seq == "[B":  # Down arrow
                    return "down"
            return "esc"
        return ch
    except Exception:
        return None


class PlayerDaemon:
    """Background media player engine running audio and listening for socket / OS commands."""

    def __init__(self, tracks: list[Path], root_dir: Path, shuffle_mode: bool = False) -> None:
        self.original_tracks = list(tracks)
        self.root_dir = root_dir
        self.shuffle_mode = shuffle_mode
        self.player_bin = get_player_command()
        self.lock = threading.RLock()
        self.running = True

        self.favorites_file = self.root_dir / ".favorites.txt"
        self.favorites = load_favorites(self.favorites_file)

        self.playlist: list[Path] = []
        self._build_playlist()

        self.current_index = 0
        self.history: list[int] = []
        self.current_process: subprocess.Popen | None = None
        self.is_paused = False
        self.repeat_mode = "ALL"
        self.flash_message: str | None = None

        # Elapsed / Seek tracking
        self.track_offset = 0.0
        self.track_start_time = time.time()
        self.paused_accumulated = 0.0
        self.pause_start_time = 0.0

        # OS media bridge
        self.os_bridge = OSMediaKeyBridge(self.handle_os_command)
        self.os_bridge.start()

        # Socket server
        self.server_sock: socket.socket | None = None
        self._setup_socket_server()

    def _build_playlist(self) -> None:
        if self.shuffle_mode:
            self.playlist = list(self.original_tracks)
            random.shuffle(self.playlist)
        else:
            self.playlist = list(self.original_tracks)

    def _setup_socket_server(self) -> None:
        if SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except Exception:
                pass

        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(str(SOCKET_PATH))
        self.server_sock.listen(5)
        self.server_sock.settimeout(0.5)

        t = threading.Thread(target=self._socket_listener_loop, daemon=True)
        t.start()

    def _socket_listener_loop(self) -> None:
        while self.running:
            try:
                conn, _ = self.server_sock.accept()
            except (socket.timeout, OSError):
                continue
            except Exception:
                break

            threading.Thread(target=self._handle_client_conn, args=(conn,), daemon=True).start()

    def _handle_client_conn(self, conn: socket.socket) -> None:
        conn.settimeout(2.0)
        try:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk

            raw_cmd = data.decode("utf-8").strip()
            response = self.process_command(raw_cmd)
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_elapsed_seconds(self) -> float:
        with self.lock:
            if self.is_paused:
                return self.track_offset + self.paused_accumulated
            return self.track_offset + self.paused_accumulated + (time.time() - self.track_start_time)

    def process_command(self, cmd: str) -> dict:
        with self.lock:
            if cmd == "PING":
                return {"status": "PONG"}

            if cmd == "STATUS":
                track = self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
                title = track.name if track else ""
                try:
                    rel_folder = track.parent.relative_to(self.root_dir) if track else ""
                    folder_str = str(rel_folder) if str(rel_folder) != "." else "root"
                except Exception:
                    folder_str = str(track.parent.name) if track else ""

                try:
                    track_key = str(track.relative_to(self.root_dir)) if track else ""
                except Exception:
                    track_key = track.name if track else ""
                is_liked = track_key in self.favorites

                flash = self.flash_message
                self.flash_message = None

                return {
                    "state": "PAUSED" if self.is_paused else "PLAYING",
                    "title": title,
                    "folder": folder_str,
                    "index": self.current_index,
                    "total": len(self.playlist),
                    "shuffle": self.shuffle_mode,
                    "repeat": self.repeat_mode,
                    "liked": is_liked,
                    "engine": self.player_bin,
                    "elapsed": int(self.get_elapsed_seconds()),
                    "flash": flash,
                    "os_active": self.os_bridge.is_active,
                }

            if cmd == "TOGGLE_PAUSE":
                self.toggle_pause()
                return {"status": "OK"}

            if cmd == "NEXT":
                self.next_track()
                return {"status": "OK"}

            if cmd == "PREV":
                self.prev_track()
                return {"status": "OK"}

            if cmd.startswith("SEEK:"):
                delta_str = cmd.split(":", 1)[1]
                try:
                    delta = float(delta_str)
                    self.seek_relative(delta)
                except ValueError:
                    pass
                return {"status": "OK"}

            if cmd == "TOGGLE_SHUFFLE":
                self.toggle_shuffle()
                return {"status": "OK"}

            if cmd == "TOGGLE_REPEAT":
                self.toggle_repeat()
                return {"status": "OK"}

            if cmd == "TOGGLE_LIKE":
                self.toggle_like()
                return {"status": "OK"}

            if cmd == "REPLAY":
                self.flash_message = "🔄 Replaying track from start"
                self.start_track(self.current_index, offset=0.0)
                return {"status": "OK"}

            if cmd.startswith("JUMP:"):
                idx_str = cmd.split(":", 1)[1]
                if idx_str.isdigit() and 0 <= int(idx_str) < len(self.playlist):
                    self.history.append(self.current_index)
                    self.current_index = int(idx_str)
                    self.start_track(self.current_index, offset=0.0)
                return {"status": "OK"}

            if cmd == "GET_QUEUE":
                items = []
                for p in self.playlist:
                    try:
                        k = str(p.relative_to(self.root_dir))
                    except Exception:
                        k = p.name
                    items.append({
                        "name": p.name,
                        "liked": k in self.favorites,
                    })
                return {
                    "playlist": items,
                    "current_index": self.current_index,
                }

            if cmd == "SHUTDOWN":
                self.stop_current_process()
                self.running = False
                self.cleanup()
                threading.Thread(target=lambda: (time.sleep(0.1), os._exit(0))).start()
                return {"status": "SHUTDOWN"}

            return {"error": "UNKNOWN_COMMAND"}

    def handle_os_command(self, cmd: str) -> None:
        with self.lock:
            if cmd == "TOGGLE_PLAY_PAUSE":
                self.toggle_pause()
            elif cmd == "PLAY" and self.is_paused:
                self.toggle_pause()
            elif cmd == "PAUSE" and not self.is_paused:
                self.toggle_pause()
            elif cmd == "NEXT":
                self.flash_message = "⏭️ OS Media Key: Next Track"
                self.next_track()
            elif cmd == "PREV":
                self.flash_message = "⏮️ OS Media Key: Previous Track"
                self.prev_track()

    def start_track(self, index: int, offset: float = 0.0) -> None:
        with self.lock:
            self.stop_current_process()
            if not (0 <= index < len(self.playlist)):
                return

            track = self.playlist[index]
            self.track_offset = max(0.0, offset)
            self.track_start_time = time.time()
            self.paused_accumulated = 0.0

            if self.player_bin == "ffplay":
                cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
                if self.track_offset > 0:
                    cmd += ["-ss", str(self.track_offset)]
                cmd.append(str(track))
            else:
                cmd = ["afplay", str(track)]

            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.is_paused = False
            self.os_bridge.update_now_playing(track.stem, str(track.parent.name), is_playing=True)

    def stop_current_process(self) -> None:
        with self.lock:
            if self.current_process is not None:
                try:
                    if self.is_paused:
                        self.current_process.send_signal(signal.SIGCONT)
                    self.current_process.terminate()
                    self.current_process.wait(timeout=0.3)
                except Exception:
                    try:
                        self.current_process.kill()
                    except Exception:
                        pass
                self.current_process = None
                self.is_paused = False
                self.os_bridge.update_now_playing("", "", is_playing=False)




    def toggle_pause(self) -> None:
        with self.lock:
            track = self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
            title = track.stem if track else ""
            artist = str(track.parent.name) if track else ""

            if self.is_paused:
                # Resuming from pause: restart at exact paused timestamp cleanly
                target_offset = self.get_elapsed_seconds()
                self.is_paused = False
                self.flash_message = "▶️ Resumed"
                self.start_track(self.current_index, offset=target_offset)
                self.os_bridge.update_now_playing(title, artist, is_playing=True)
            else:
                # Pausing: terminate audio process immediately to eliminate CoreAudio ring buffer stutter/repeats
                self.paused_accumulated += (time.time() - self.track_start_time)
                self.stop_current_process()
                self.is_paused = True
                self.flash_message = "⏸️ Paused"
                self.os_bridge.update_now_playing(title, artist, is_playing=False)

    def seek_relative(self, delta_seconds: float) -> None:
        """Seek forward or backward by delta_seconds."""
        with self.lock:
            if self.player_bin != "ffplay":
                self.flash_message = "⚠️ Seeking requires ffplay"
                return

            current = self.get_elapsed_seconds()
            target_time = max(0.0, current + delta_seconds)
            prefix = "+" if delta_seconds > 0 else ""
            self.flash_message = f"⏩ Seek {prefix}{int(delta_seconds)}s (Jumped to {int(target_time)}s)"

            if self.is_paused:
                self.track_offset = target_time
                self.paused_accumulated = 0.0
                self.track_start_time = time.time()
            else:
                self.start_track(self.current_index, offset=target_time)

    def next_track(self) -> None:
        with self.lock:
            self.history.append(self.current_index)
            if self.current_index + 1 < len(self.playlist):
                self.current_index += 1
            else:
                self.current_index = 0
                if self.shuffle_mode:
                    random.shuffle(self.playlist)
            self.start_track(self.current_index, offset=0.0)

    def prev_track(self) -> None:
        with self.lock:
            if self.history:
                self.current_index = self.history.pop()
            elif self.current_index > 0:
                self.current_index -= 1
            else:
                self.current_index = len(self.playlist) - 1
            self.start_track(self.current_index, offset=0.0)

    def toggle_shuffle(self) -> None:
        with self.lock:
            if not self.playlist:
                return

            current_track = self.playlist[self.current_index]
            self.shuffle_mode = not self.shuffle_mode

            if self.shuffle_mode:
                remaining = [t for i, t in enumerate(self.playlist) if i != self.current_index]
                random.shuffle(remaining)
                self.playlist = [current_track] + remaining
                self.current_index = 0
                self.flash_message = "🔀 Shuffle Mode: ON"
            else:
                self.playlist = list(self.original_tracks)
                try:
                    self.current_index = self.playlist.index(current_track)
                except ValueError:
                    self.current_index = 0
                self.flash_message = "▶️ Sequential Order: ON"

    def toggle_repeat(self) -> None:
        with self.lock:
            modes = ["ALL", "ONE", "OFF"]
            idx = (modes.index(self.repeat_mode) + 1) % len(modes)
            self.repeat_mode = modes[idx]
            if self.repeat_mode == "ALL":
                self.flash_message = "🔁 Repeat: ALL (Loop entire playlist)"
            elif self.repeat_mode == "ONE":
                self.flash_message = "🔂 Repeat: ONE (Loop current song)"
            else:
                self.flash_message = "➡️ Repeat: OFF (Stop at end of playlist)"

    def toggle_like(self) -> None:
        with self.lock:
            if not (0 <= self.current_index < len(self.playlist)):
                return

            track = self.playlist[self.current_index]
            try:
                track_key = str(track.relative_to(self.root_dir))
            except Exception:
                track_key = track.name

            if track_key in self.favorites:
                self.favorites.remove(track_key)
                self.flash_message = f"💔 Unliked: {track.stem[:30]}"
            else:
                self.favorites.add(track_key)
                self.flash_message = f"❤️ Liked: {track.stem[:30]}"

            save_favorites(self.favorites_file, self.favorites)

    def run_daemon_loop(self) -> None:
        """Main lifecycle loop of background player daemon."""
        self.start_track(self.current_index, offset=0.0)

        while self.running:
            with self.lock:
                if not self.is_paused and self.current_process is not None and self.current_process.poll() is not None:
                    # Natural track end
                    if self.repeat_mode == "ONE":
                        self.start_track(self.current_index, offset=0.0)
                    else:
                        self.history.append(self.current_index)
                        if self.current_index + 1 < len(self.playlist):
                            self.current_index += 1
                            self.start_track(self.current_index, offset=0.0)
                        else:
                            if self.repeat_mode == "ALL":
                                self.current_index = 0
                                if self.shuffle_mode:
                                    random.shuffle(self.playlist)
                                self.start_track(self.current_index, offset=0.0)
                            else:
                                self.stop_current_process()
                                self.running = False
                                break

            time.sleep(0.1)

        self.cleanup()

    def cleanup(self) -> None:
        self.os_bridge.stop()
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
        if SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except Exception:
                pass


class PlayerClient:
    """Foreground interactive terminal UI connected to the background player daemon."""

    def __init__(self) -> None:
        self.raw_term = RawTerminal()
        self.anim_tick = 0
        self.cols = 24
        self.max_height = 8
        self.bar_heights = [1.0] * self.cols
        self.peak_heights = [1.0] * self.cols

    def update_physics(self, is_paused: bool) -> None:
        """Update bar heights and floating peak caps with non-repeating organic motion."""
        if is_paused:
            for c in range(self.cols):
                self.bar_heights[c] = max(1.0, self.bar_heights[c] - 1.5)
                self.peak_heights[c] = max(1.0, self.peak_heights[c] - 0.8)
            return

        t = self.anim_tick * 0.35
        for c in range(self.cols):
            # Incommensurate irrational frequency waves (multi-frequency chaotic harmonics)
            irrational = (
                math.sin(t * 1.414 + c * 0.65) * 0.35
                + math.sin(t * 2.718 - c * 0.38) * 0.30
                + math.cos(t * 3.1415 + c * 1.12) * 0.25
                + math.sin(t * 1.732 + c * 0.27) * 0.20
            )
            noise = random.uniform(0.0, 1.0)
            rel_pos = c / self.cols

            # Organic audio band behavior with random impulses (never repeating)
            if rel_pos < 0.25:
                # Bass frequency: deep heavy kicks with random beat drops
                kick = 4.8 if random.random() < 0.35 else 0.4
                target = 2.0 + (self.max_height - 3) * (irrational * 0.5 + 0.5) + kick * noise
            elif rel_pos < 0.65:
                # Mids: active rhythmic bounce
                kick = 3.6 if random.random() < 0.45 else 0.8
                target = 1.5 + (self.max_height - 3) * (irrational * 0.5 + 0.5) + kick * noise
            else:
                # Treble / Highs: sparkling random shimmer
                target = 1.0 + (self.max_height - 3) * (irrational * 0.5 + 0.5) + random.uniform(0.5, 4.2)

            target = max(1.0, min(float(self.max_height), target))

            # Physics: Fast attack rise, smooth gravity fall
            if target > self.bar_heights[c]:
                self.bar_heights[c] = self.bar_heights[c] * 0.35 + target * 0.65
            else:
                self.bar_heights[c] = max(1.0, self.bar_heights[c] - 1.2)

            # Floating peak caps
            if self.bar_heights[c] >= self.peak_heights[c]:
                self.peak_heights[c] = self.bar_heights[c]
            else:
                self.peak_heights[c] = max(self.bar_heights[c], self.peak_heights[c] - 0.35)

    def get_equalizer_block(self, is_paused: bool) -> list[str]:
        """Generate 8-line tall vertical audio equalizer blocks with non-repeating beats and floating peak caps."""
        self.update_physics(is_paused)

        if is_paused and all(h <= 1.2 for h in self.bar_heights):
            lines = ["   " + " " * 48] * (self.max_height - 1)
            flatline = "   " + " ".join(["\033[90m·\033[0m"] * self.cols) + "   \033[1;33m[ ⏸ PAUSED ]\033[0m"
            lines.append(flatline)
            return lines

        beat_note = "♫" if (self.anim_tick // 4) % 2 == 0 else "♬"
        lines = []
        for r in range(self.max_height, 0, -1):
            color = EQUALIZER_COLORS[self.max_height - r]
            row_items = []
            for c in range(self.cols):
                h = int(round(self.bar_heights[c]))
                pk = int(round(self.peak_heights[c]))
                if h >= r:
                    row_items.append(f"{color}█\033[0m")
                elif pk == r and pk > h:
                    row_items.append("\033[1;37m▔\033[0m")
                elif h + 1 == r:
                    row_items.append("\033[90m·\033[0m")
                else:
                    row_items.append(" ")
            tag = f"   \033[1;32m[ {beat_note} BEATS ]\033[0m" if r == self.max_height // 2 else ""
            lines.append("   " + " ".join(row_items) + tag)
        return lines

    def render(self, status: dict, clear_screen: bool = False) -> None:
        is_paused = (status.get("state") == "PAUSED")
        status_icon = "\033[1;33m⏸ PAUSED\033[0m" if is_paused else "\033[1;32m▶ PLAYING\033[0m"
        shuffle_badge = "\033[1;32mON\033[0m" if status.get("shuffle") else "\033[1;33mOFF\033[0m"
        repeat_badge = f"\033[1;36m{status.get('repeat', 'ALL')}\033[0m"
        liked_badge = " \033[1;31m❤️ LIKED\033[0m" if status.get("liked") else ""
        os_badge = " \033[1;32m[🎧 OS Media Keys Active]\033[0m" if status.get("os_active") else ""
        pos = status.get("index", 0) + 1
        total = status.get("total", 0)
        elapsed = status.get("elapsed", 0)
        elapsed_str = f"{elapsed // 60}:{elapsed % 60:02d}"

        if clear_screen:
            print("\033[2J\033[H", end="")
        else:
            print("\033[H", end="")

        print("\033[1;36m========================================================================\033[0m")
        print(f" {status_icon}  [\033[1m{pos}/{total}\033[0m]  |  SHUFFLE: {shuffle_badge}  |  REPEAT: {repeat_badge}{liked_badge}")
        print("\033[1;36m========================================================================\033[0m")
        print(f"  \033[1mTitle:\033[0m   {status.get('title', '')}")
        print(f"  \033[1mFolder:\033[0m  {status.get('folder', '')}  (\033[1;34mElapsed:\033[0m {elapsed_str})")
        print(f"  \033[1mEngine:\033[0m  {status.get('engine', '')}{os_badge}")
        for eq_line in self.get_equalizer_block(is_paused):
            print(eq_line)

        if status.get("flash"):
            print("\033[1;33m------------------------------------------------------------------------\033[0m")
            print(f"  {status.get('flash')}")

        print("\033[1;36m------------------------------------------------------------------------\033[0m")
        print("  \033[1mControls:\033[0m")
        print("   [\033[1mSpace\033[0m]    Pause / Resume       [\033[1mn\033[0m/→]       Next Track")
        print("   [\033[1mp\033[0m/←]      Previous Track       [\033[1m5\033[0m / \033[1m0\033[0m]     Seek +5s / +10s ([,] -5s)")
        print("   [\033[1ms\033[0m]        Toggle Shuffle       [\033[1mt\033[0m]         Repeat Mode (All/1)")
        print("   [\033[1m/\033[0m or \033[1mf\033[0m]   Search Songs         [\033[1mk\033[0m]         Like / Favorite (❤️)")
        print("   [\033[1ml\033[0m]        List Queue (Next)    [\033[1mr\033[0m]         Replay Song")
        print("   [\033[1mb\033[0m / \033[1mm\033[0m]    \033[1;32mBack to Main Menu (Keep Playing in Background)\033[0m")
        print("   [\033[1mq\033[0m]        \033[1;31mStop Player & Exit\033[0m")
        print("  \033[2m🎧 Hardware OS Buttons: F7/Prev, F8/Play-Pause, F9/Next, AirPods supported\033[0m")
        print("\033[1;36m========================================================================\033[0m")

    def show_paginated_queue(self) -> None:
        """Display interactive paginated list view with 'next' option to see more upcoming tracks."""
        q_data = send_daemon_command("GET_QUEUE")
        if not q_data or "playlist" not in q_data:
            return

        playlist = q_data["playlist"]
        current_idx = q_data.get("current_index", 0)
        total_tracks = len(playlist)
        if total_tracks == 0:
            return

        page_size = 10
        total_pages = max(1, math.ceil(total_tracks / page_size))
        current_page = current_idx // page_size

        while True:
            start = current_page * page_size
            end = min(start + page_size, total_tracks)
            page_items = playlist[start:end]

            print("\033[2J\033[H", end="")
            print("\033[1;34m========================================================================\033[0m")
            print(f" \033[1m📋 Upcoming Tracks in Queue\033[0m  (Page {current_page + 1}/{total_pages})  [Total: {total_tracks} songs]")
            print("\033[1;34m========================================================================\033[0m")

            for i, item in enumerate(page_items):
                global_idx = start + i
                is_curr = (global_idx == current_idx)
                prefix = "\033[1;32m▶\033[0m" if is_curr else " "
                badge = " \033[1;31m❤️\033[0m" if item.get("liked") else ""
                cur_note = " \033[1;32m[PLAYING NOW]\033[0m" if is_curr else ""
                print(f" {prefix} [\033[1m{i+1:2d}\033[0m] #{global_idx+1:2d}: {item['name']}{badge}{cur_note}")

            print("\033[1;34m------------------------------------------------------------------------\033[0m")
            print("  Options:")
            if current_page + 1 < total_pages:
                print("   [\033[1mn\033[0m] Next Page (Show More Coming Soon)    [\033[1mp\033[0m] Previous Page")
            else:
                print("   [\033[1mp\033[0m] Previous Page                       [\033[2mEnd of Queue\033[0m]")
            print("   [\033[1m1-10\033[0m] Jump to track number on this page")
            print("   [\033[1mq\033[0m/Enter/Esc] Return to Player View")
            print("\033[1;34m========================================================================\033[0m")

            key = read_key_nonblocking(timeout_sec=0.2)
            if not key:
                continue

            if key in {"n", "N", "right"}:
                if current_page + 1 < total_pages:
                    current_page += 1
                else:
                    current_page = 0  # Wrap around
            elif key in {"p", "P", "left"}:
                if current_page > 0:
                    current_page -= 1
                else:
                    current_page = total_pages - 1
            elif key.isdigit():
                digit = int(key)
                if digit == 0 and len(page_items) >= 10:
                    jump_idx = start + 9
                    send_daemon_command(f"JUMP:{jump_idx}")
                    break
                elif 1 <= digit <= len(page_items):
                    jump_idx = start + digit - 1
                    send_daemon_command(f"JUMP:{jump_idx}")
                    break
            elif key in {"q", "Q", "\r", "\n", "esc"}:
                break

    def search_and_jump(self) -> None:
        """Search queue and jump to match."""
        q_data = send_daemon_command("GET_QUEUE")
        if not q_data or "playlist" not in q_data:
            return

        playlist = q_data["playlist"]
        self.raw_term.restore()

        print("\n\033[1;36m" + "=" * 70 + "\033[0m")
        print(" \033[1m🔍 Search Tracks in Playlist\033[0m (Press Enter without text to cancel)")
        print("\033[1;36m" + "=" * 70 + "\033[0m")

        try:
            query = input("Enter search query: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            query = ""

        if not query:
            self.raw_term.enable_cbreak()
            return

        matches = [
            (idx, item) for idx, item in enumerate(playlist)
            if query in item["name"].lower()
        ]

        if not matches:
            print(f"\n\033[1;31m[!] No tracks found matching '{query}'.\033[0m")
            time.sleep(1.2)
            self.raw_term.enable_cbreak()
            return

        print(f"\nFound {len(matches)} matching track(s) (showing up to 15):")
        max_show = min(len(matches), 15)
        for i in range(max_show):
            orig_idx, item = matches[i]
            print(f"  [{i+1:2d}] #{orig_idx+1}: {item['name']}")

        try:
            choice = input(f"\nSelect track [1-{max_show}] to play (or Enter to cancel): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= max_show:
                selected_orig_idx = matches[int(choice) - 1][0]
                send_daemon_command(f"JUMP:{selected_orig_idx}")
        except (EOFError, KeyboardInterrupt):
            pass

        self.raw_term.enable_cbreak()

    def run(self) -> None:
        with self.raw_term:
            first_render = True

            while True:
                status = send_daemon_command("STATUS", timeout=0.5)
                if not status:
                    # Daemon exited or stopped
                    print("\n\033[1;32mPlayer daemon has stopped.\033[0m\n")
                    break

                if not (status.get("state") == "PAUSED"):
                    self.anim_tick += 1

                self.render(status, clear_screen=first_render)
                first_render = False

                key = read_key_nonblocking(timeout_sec=0.1)
                if not key:
                    continue

                if key in {" "}:
                    send_daemon_command("TOGGLE_PAUSE")
                elif key in {"n", "right"}:
                    send_daemon_command("NEXT")
                    first_render = True
                elif key in {"p", "left"}:
                    send_daemon_command("PREV")
                    first_render = True
                elif key in {"5", "]"}:
                    send_daemon_command("SEEK:5")
                elif key in {"0", "}"}:
                    send_daemon_command("SEEK:10")
                elif key in {",", "["}:
                    send_daemon_command("SEEK:-5")
                elif key in {"s", "S"}:
                    send_daemon_command("TOGGLE_SHUFFLE")
                elif key in {"t", "T"}:
                    send_daemon_command("TOGGLE_REPEAT")
                elif key in {"k", "K", "+"}:
                    send_daemon_command("TOGGLE_LIKE")
                elif key in {"r", "R"}:
                    send_daemon_command("REPLAY")
                elif key in {"/", "f", "F"}:
                    self.search_and_jump()
                    first_render = True
                elif key in {"l", "L"}:
                    self.show_paginated_queue()
                    first_render = True
                elif key in {"b", "B", "m", "M"}:
                    # Back to main menu without stopping!
                    print("\n\033[1;32m♫ Player running in background. Returning to main menu...\033[0m\n")
                    time.sleep(0.5)
                    break
                elif key in {"q", "Q", "x", "X"}:
                    # Stop player daemon completely
                    send_daemon_command("SHUTDOWN")
                    print("\n\033[1;32mPlayer stopped.\033[0m\n")
                    time.sleep(0.3)
                    break


def run_daemon(target_path: Path, shuffle: bool, favorites: bool) -> None:
    tracks = find_tracks(target_path)
    if not tracks:
        sys.exit("No playable tracks found.")

    if favorites:
        fav_file = target_path / ".favorites.txt"
        if not fav_file.exists():
            fav_file = PROJECT_ROOT / "downloads" / ".favorites.txt"
        favs = load_favorites(fav_file)
        filtered = [t for t in tracks if str(t.relative_to(target_path)) in favs or t.name in favs]
        if filtered:
            tracks = filtered

    daemon = PlayerDaemon(tracks, root_dir=target_path, shuffle_mode=shuffle)
    daemon.run_daemon_loop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Terminal Audio Player with Background Playback, Seeking, and Beats.")
    parser.add_argument("target", nargs="?", default=None, help="Folder to play")
    parser.add_argument("--shuffle", "-s", action="store_true", help="Shuffle mode")
    parser.add_argument("--favorites", "--likes", action="store_true", help="Play liked songs only")
    parser.add_argument("--daemon", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--status", action="store_true", help="Print current player status (PLAYING|track, PAUSED|track, or STOPPED)")
    parser.add_argument("--stop", action="store_true", help="Stop running player daemon")
    parser.add_argument("--attach", action="store_true", help="Attach to running player")
    args = parser.parse_args()

    # 1. Status query
    if args.status:
        if not is_daemon_alive():
            print("STOPPED")
            sys.exit(0)
        st = send_daemon_command("STATUS", timeout=0.3)
        if not st:
            print("STOPPED")
        else:
            state = st.get("state", "PLAYING")
            title = st.get("title", "Unknown")
            print(f"{state}:{title}")
        sys.exit(0)

    # 2. Stop query
    if args.stop:
        if is_daemon_alive():
            send_daemon_command("SHUTDOWN", timeout=0.5)
            print("Player stopped.")
        else:
            print("Player is not running.")
        sys.exit(0)

    # 3. Daemon internal worker
    if args.daemon:
        target_path = Path(args.target).resolve() if args.target else PROJECT_ROOT / "downloads"
        run_daemon(target_path, shuffle=args.shuffle, favorites=args.favorites)
        sys.exit(0)

    # 4. Interactive launch or attach
    if is_daemon_alive():
        # Daemon is already running! Connect client immediately without restarting
        client = PlayerClient()
        client.run()
        sys.exit(0)

    # Daemon not running -> launch it in background
    target_path = Path(args.target).resolve() if args.target else PROJECT_ROOT / "downloads"
    tracks = find_tracks(target_path)
    if not tracks:
        sys.exit(f"No playable tracks found in: {target_path}")

    daemon_cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--daemon",
        str(target_path),
    ]
    if args.shuffle:
        daemon_cmd.append("--shuffle")
    if args.favorites:
        daemon_cmd.append("--favorites")

    # Start daemon in background
    subprocess.Popen(
        daemon_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for socket to become ready
    for _ in range(30):
        time.sleep(0.05)
        if is_daemon_alive():
            break

    # Connect client
    client = PlayerClient()
    client.run()


if __name__ == "__main__":
    main()
