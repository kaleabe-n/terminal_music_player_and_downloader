#!/usr/bin/env bash

# ==============================================================================
# All-In-One Media Downloader & Library Manager
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"
YOUTUBE_SCRIPT="$SCRIPT_DIR/youtube_downloader.py"
SPOTIFY_SCRIPT="$SCRIPT_DIR/spotify_downloader.py"
CLEANER_SCRIPT="$SCRIPT_DIR/clean_library.py"
PLAYER_SCRIPT="$SCRIPT_DIR/player.py"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

# ANSI Colors
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
NC="\033[0m" # No Color

# ------------------------------------------------------------------------------
# 1. Environment & Dependency Initialization
# ------------------------------------------------------------------------------
init_environment() {
    if ! command -v python3 &>/dev/null; then
        echo -e "${RED}[ERROR] python3 is not installed or not in PATH.${NC}"
        echo "Please install Python 3.10+ to continue."
        exit 1
    fi

    # Create virtual environment if missing
    if [ ! -d "$VENV_DIR" ] || [ ! -x "$PYTHON_BIN" ]; then
        echo -e "${YELLOW}[i] Virtual environment not found. Setting up at $VENV_DIR...${NC}"
        python3 -m venv "$VENV_DIR"
        echo -e "${GREEN}[✓] Created virtual environment.${NC}"
        
        if [ -f "$REQUIREMENTS_FILE" ]; then
            echo -e "${YELLOW}[i] Installing dependencies from requirements.txt...${NC}"
            "$PIP_BIN" install --upgrade pip
            "$PIP_BIN" install -r "$REQUIREMENTS_FILE"
            echo -e "${GREEN}[✓] Dependencies installed.${NC}"
        fi
    fi

    # Check for ffmpeg
    if ! command -v ffmpeg &>/dev/null; then
        echo -e "${YELLOW}[WARNING] 'ffmpeg' is not found in your PATH.${NC}"
        echo -e "${YELLOW}          ffmpeg is required for audio conversion and video merging.${NC}"
        if [ -t 0 ] && command -v brew &>/dev/null; then
            read -r -p "Would you like to install ffmpeg now via Homebrew? (y/N): " install_ffmpeg
            if [[ "$install_ffmpeg" =~ ^[yY]([eE][sS])?$ ]]; then
                echo -e "${CYAN}Running: brew install ffmpeg...${NC}"
                brew install ffmpeg || echo -e "${RED}ffmpeg install failed. You can install it manually: brew install ffmpeg${NC}"
            fi
        else
            echo -e "${YELLOW}Install ffmpeg via Homebrew: ${BOLD}brew install ffmpeg${NC}\n"
        fi
    fi
}

print_header() {
    clear 2>/dev/null || true
    echo -e "${CYAN}${BOLD}"
    echo "========================================================"
    echo "        All-in-One Media Downloader & Library Manager   "
    echo "========================================================"
    echo -e "${NC}"
}

# ------------------------------------------------------------------------------
# 2. YouTube Search & Download Flow
# ------------------------------------------------------------------------------
search_youtube_flow() {
    print_header
    echo -e "${CYAN}${BOLD}--- Search YouTube & Download (Top 15 Results) ---${NC}\n"

    # Search Query
    local search_query=""
    while [ -z "$search_query" ]; do
        echo -e "${BOLD}Enter YouTube search query (or 'b' to go back):${NC}"
        read -r -p "> " search_query
        search_query=$(echo "$search_query" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

        if [[ "$search_query" == "b" || "$search_query" == "back" || "$search_query" == "q" || "$search_query" == "quit" ]]; then
            return 0
        fi

        if [ -z "$search_query" ]; then
            echo -e "${YELLOW}[!] Search query cannot be empty. Please try again.${NC}\n"
        fi
    done

    # Format
    echo ""
    echo -e "${BOLD}Select download format:${NC}"
    echo "  1) MP3 (Audio only - Default)"
    echo "  2) MP4 (Video)"
    read -r -p "Choice [1/2] (Default: 1): " format_choice
    format_choice=$(echo "$format_choice" | tr '[:upper:]' '[:lower:]' | tr -d ' ')

    local media_type="mp3"
    if [ "$format_choice" = "2" ] || [ "$format_choice" = "mp4" ]; then
        media_type="mp4"
    fi

    # Quality if MP4
    local quality="best"
    if [ "$media_type" = "mp4" ]; then
        echo ""
        echo -e "${BOLD}Select video quality:${NC}"
        echo "  1) best  (Highest resolution available - Default)"
        echo "  2) 1080p (Full HD)"
        echo "  3) 720p  (HD)"
        echo "  4) 480p  (Standard definition)"
        echo "  5) 360p  (Lower resolution / smaller size)"
        echo "  6) worst (Lowest file size)"
        read -r -p "Choice [1-6 or resolution name] (Default: 1): " quality_choice
        quality_choice=$(echo "$quality_choice" | tr '[:upper:]' '[:lower:]' | tr -d ' ')

        case "$quality_choice" in
            2|"1080"|"1080p") quality="1080p" ;;
            3|"720"|"720p")   quality="720p" ;;
            4|"480"|"480p")   quality="480p" ;;
            5|"360"|"360p")   quality="360p" ;;
            6|"worst")        quality="worst" ;;
            *)                quality="best" ;;
        esac
    fi

    local cmd_args=("--search" "$search_query" "--limit" "15" "--type" "$media_type")
    if [ "$media_type" = "mp4" ]; then
        cmd_args+=("--quality" "$quality")
    fi

    echo ""
    set +e
    "$PYTHON_BIN" "$YOUTUBE_SCRIPT" "${cmd_args[@]}"
    local exit_code=$?
    set -e

    if [ $exit_code -eq 0 ]; then
        echo -e "\n${GREEN}${BOLD}[✓] Finished!${NC}"
        echo -e "Files saved in: ${BOLD}$SCRIPT_DIR/downloads/$media_type${NC}\n"

        read -r -p "Clean filenames now (strip numbers & remove duplicates)? (y/N, Default: N): " do_clean
        if [[ "$do_clean" =~ ^[yY]([eE][sS])?$ ]]; then
            "$PYTHON_BIN" "$CLEANER_SCRIPT" --target "$SCRIPT_DIR/downloads/$media_type" --yes
        fi
    fi

    echo ""
    read -r -p "Press Enter to return to menu (or 's' to search again): " next_act
    next_act=$(echo "$next_act" | tr -d ' ')
    if [[ "$next_act" =~ ^[sS]$ ]]; then
        search_youtube_flow
    fi
}

# ------------------------------------------------------------------------------
# 3. Spotify Download Flow
# ------------------------------------------------------------------------------
download_spotify_flow() {
    local spotify_url="$1"
    echo -e "\n${GREEN}${BOLD}--- Spotify Downloader ---${NC}"

    # Format
    echo -e "${BOLD}Select audio format:${NC}"
    echo "  1) MP3 (Default)"
    echo "  2) M4A (AAC)"
    echo "  3) FLAC (Lossless)"
    read -r -p "Choice [1-3] (Default: 1): " format_choice
    format_choice=$(echo "$format_choice" | tr -d ' ')

    local format="mp3"
    case "$format_choice" in
        2) format="m4a" ;;
        3) format="flac" ;;
        *) format="mp3" ;;
    esac

    # Bitrate
    local bitrate="320k"
    if [ "$format" = "mp3" ] || [ "$format" = "m4a" ]; then
        echo ""
        echo -e "${BOLD}Select audio quality:${NC}"
        echo "  1) 320 kbps (High Quality - Default)"
        echo "  2) 256 kbps"
        echo "  3) 192 kbps"
        echo "  4) Auto"
        read -r -p "Choice [1-4] (Default: 1): " bitrate_choice
        bitrate_choice=$(echo "$bitrate_choice" | tr -d ' ')

        case "$bitrate_choice" in
            2) bitrate="256k" ;;
            3) bitrate="192k" ;;
            4) bitrate="auto" ;;
            *) bitrate="320k" ;;
        esac
    fi

    echo ""
    echo -e "${BLUE}${BOLD}--- Starting Download ---${NC}"
    echo -e "  URL:     $spotify_url"
    echo -e "  Format:  $(echo "$format" | tr '[:lower:]' '[:upper:]') ($bitrate)"
    echo -e "  Folder:  downloads/spotify/"
    echo -e "${BLUE}-------------------------${NC}\n"

    set +e
    "$PYTHON_BIN" "$SPOTIFY_SCRIPT" "$spotify_url" --format "$format" --bitrate "$bitrate"
    local exit_code=$?
    set -e

    if [ $exit_code -eq 0 ]; then
        echo -e "\n${GREEN}${BOLD}[✓] Spotify download completed successfully!${NC}"
        echo -e "Files saved in: ${BOLD}$SCRIPT_DIR/downloads/spotify${NC}\n"
    else
        echo -e "\n${RED}${BOLD}[✗] Download ended with errors (exit code: $exit_code).${NC}\n"
    fi
}

# ------------------------------------------------------------------------------
# 4. YouTube Download Flow
# ------------------------------------------------------------------------------
download_youtube_flow() {
    local youtube_url="$1"
    echo -e "\n${CYAN}${BOLD}--- YouTube Downloader ---${NC}"

    # Format
    echo -e "${BOLD}Select download format:${NC}"
    echo "  1) MP4 (Video)"
    echo "  2) MP3 (Audio only - Default)"
    read -r -p "Choice [1/2] (Default: 2): " format_choice
    format_choice=$(echo "$format_choice" | tr '[:upper:]' '[:lower:]' | tr -d ' ')

    local media_type="mp3"
    if [ "$format_choice" = "1" ] || [ "$format_choice" = "mp4" ]; then
        media_type="mp4"
    fi

    # Quality if MP4
    local quality="best"
    if [ "$media_type" = "mp4" ]; then
        echo ""
        echo -e "${BOLD}Select video quality:${NC}"
        echo "  1) best  (Highest resolution available - Default)"
        echo "  2) 1080p (Full HD)"
        echo "  3) 720p  (HD)"
        echo "  4) 480p  (Standard definition)"
        echo "  5) 360p  (Lower resolution / smaller size)"
        echo "  6) worst (Lowest file size)"
        read -r -p "Choice [1-6 or resolution name] (Default: 1): " quality_choice
        quality_choice=$(echo "$quality_choice" | tr '[:upper:]' '[:lower:]' | tr -d ' ')

        case "$quality_choice" in
            2|"1080"|"1080p") quality="1080p" ;;
            3|"720"|"720p")   quality="720p" ;;
            4|"480"|"480p")   quality="480p" ;;
            5|"360"|"360p")   quality="360p" ;;
            6|"worst")        quality="worst" ;;
            *)                quality="best" ;;
        esac
    fi

    # Playlist detection
    echo ""
    local has_playlist_param=false
    if echo "$youtube_url" | grep -qE "([?&]list=|/playlist)"; then
        has_playlist_param=true
    fi

    local is_playlist=false
    if [ "$has_playlist_param" = true ]; then
        echo -e "${YELLOW}[!] Playlist or Mix detected in URL.${NC}"
        read -r -p "Download ENTIRE playlist/mix? (Y/n, Default: Y): " playlist_choice
        playlist_choice=$(echo "$playlist_choice" | tr -d ' ')
        if [[ "$playlist_choice" =~ ^[nN]([oO])?$ ]]; then
            is_playlist=false
        else
            is_playlist=true
        fi
    else
        read -r -p "Is this a playlist and do you want to download ALL videos in it? (y/N, Default: N): " playlist_choice
        playlist_choice=$(echo "$playlist_choice" | tr -d ' ')
        if [[ "$playlist_choice" =~ ^[yY]([eE][sS])?$ ]]; then
            is_playlist=true
        fi
    fi

    local max_items_input=""
    local cookies_browser=""
    if [ "$is_playlist" = true ]; then
        echo ""
        echo -e "${BOLD}Max items to download (Press Enter for ALL, or specify a limit like 15):${NC}"
        read -r -p "> " max_items_input
        max_items_input=$(echo "$max_items_input" | tr -d ' ')

        echo ""
        read -r -p "Is this a private playlist on your YouTube account? (y/N, Default: N): " is_private
        is_private=$(echo "$is_private" | tr -d ' ')
        if [[ "$is_private" =~ ^[yY]([eE][sS])?$ ]]; then
            echo -e "Which browser are you logged into YouTube on?"
            echo "  1) Chrome (Default)"
            echo "  2) Safari"
            echo "  3) Firefox"
            echo "  4) Brave"
            read -r -p "Browser [1-4 or name] (Default: 1): " browser_choice
            browser_choice=$(echo "$browser_choice" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
            case "$browser_choice" in
                2|"safari")  cookies_browser="safari" ;;
                3|"firefox") cookies_browser="firefox" ;;
                4|"brave")   cookies_browser="brave" ;;
                *)           cookies_browser="chrome" ;;
            esac
        fi
    fi

    # Display summary
    echo ""
    echo -e "${BLUE}${BOLD}--- Download Summary ---${NC}"
    echo -e "  ${BOLD}URL:${NC}        $youtube_url"
    echo -e "  ${BOLD}Format:${NC}     $(echo "$media_type" | tr '[:lower:]' '[:upper:]')"
    if [ "$media_type" = "mp4" ]; then
        echo -e "  ${BOLD}Quality:${NC}    $quality"
    fi
    echo -e "  ${BOLD}Playlist:${NC}   $( [ "$is_playlist" = true ] && echo "Yes (all items)" || echo "No (single item)" )"
    if [ -n "$max_items_input" ] && [ "$max_items_input" -gt 0 ] 2>/dev/null; then
        echo -e "  ${BOLD}Max Items:${NC}  $max_items_input"
    fi
    if [ -n "$cookies_browser" ]; then
        echo -e "  ${BOLD}Cookies:${NC}    $cookies_browser"
    fi
    echo -e "${BLUE}------------------------${NC}\n"

    # Command arguments
    local cmd_args=("$youtube_url" "--type" "$media_type")
    if [ "$media_type" = "mp4" ]; then
        cmd_args+=("--quality" "$quality")
    fi
    if [ "$is_playlist" = true ]; then
        cmd_args+=("--playlist")
        if [ -n "$max_items_input" ] && [ "$max_items_input" -gt 0 ] 2>/dev/null; then
            cmd_args+=("--max-items" "$max_items_input")
        fi
        if [ -n "$cookies_browser" ]; then
            cmd_args+=("--cookies-from-browser" "$cookies_browser")
        fi
    fi

    echo -e "${CYAN}[*] Starting download...${NC}"
    set +e
    "$PYTHON_BIN" "$YOUTUBE_SCRIPT" "${cmd_args[@]}"
    local exit_code=$?
    set -e

    if [ $exit_code -eq 0 ]; then
        echo -e "\n${GREEN}${BOLD}[✓] Download completed successfully!${NC}"
        echo -e "Files saved in: ${BOLD}$SCRIPT_DIR/downloads/$media_type${NC}\n"

        read -r -p "Clean filenames now (strip numbers & remove duplicates)? (y/N, Default: N): " do_clean
        if [[ "$do_clean" =~ ^[yY]([eE][sS])?$ ]]; then
            "$PYTHON_BIN" "$CLEANER_SCRIPT" --target "$SCRIPT_DIR/downloads/$media_type" --yes
        fi
        echo ""
    else
        echo -e "\n${RED}${BOLD}[✗] Download ended with errors (exit code: $exit_code).${NC}\n"
    fi
}

# ------------------------------------------------------------------------------
# 5. Universal Downloader Dispatcher
# ------------------------------------------------------------------------------
download_flow() {
    while true; do
        print_header
        echo -e "${BOLD}Enter YouTube or Spotify URL (or 'b' to go back, 'q' to quit):${NC}"
        read -r -p "> " url_input
        url_input=$(echo "$url_input" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

        if [[ "$url_input" == "q" || "$url_input" == "quit" || "$url_input" == "exit" ]]; then
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
        fi

        if [[ "$url_input" == "b" || "$url_input" == "back" ]]; then
            return 0
        fi

        if [ -z "$url_input" ]; then
            echo -e "${RED}[!] URL cannot be empty. Please try again.${NC}\n"
            sleep 1
            continue
        fi

        # Route URL
        if echo "$url_input" | grep -qE "spotify\.com|spotify\.link"; then
            download_spotify_flow "$url_input"
        else
            download_youtube_flow "$url_input"
        fi

        read -r -p "Download another URL? (y/N): " another
        if [[ ! "$another" =~ ^[yY]([eE][sS])?$ ]]; then
            break
        fi
    done
}

# ------------------------------------------------------------------------------
# 6. Library Cleaner & Deduplicator Flow
# ------------------------------------------------------------------------------
cleanup_flow() {
    print_header
    echo -e "${YELLOW}${BOLD}--- Library Cleaner & Duplicate Remover ---${NC}\n"

    # Target folder
    echo -e "${BOLD}Select target folder to clean:${NC}"
    echo "  1) Entire downloads directory (downloads/) [Default]"
    echo "  2) MP3 only (downloads/mp3/)"
    echo "  3) Spotify only (downloads/spotify/)"
    echo "  4) MP4 only (downloads/mp4/)"
    echo "  5) Custom path"
    read -r -p "Choice [1-5] (Default: 1): " target_choice
    target_choice=$(echo "$target_choice" | tr -d ' ')

    local target_dir="$SCRIPT_DIR/downloads"
    case "$target_choice" in
        2) target_dir="$SCRIPT_DIR/downloads/mp3" ;;
        3) target_dir="$SCRIPT_DIR/downloads/spotify" ;;
        4) target_dir="$SCRIPT_DIR/downloads/mp4" ;;
        5)
            read -r -p "Enter custom folder path: " custom_dir
            target_dir="$custom_dir"
            ;;
        *) target_dir="$SCRIPT_DIR/downloads" ;;
    esac

    # Scope
    echo ""
    echo -e "${BOLD}Select duplicate detection scope:${NC}"
    echo "  1) Global (Find duplicates across all playlists/folders) [Default]"
    echo "  2) Folder-only (Only remove duplicates within each folder separately)"
    read -r -p "Choice [1/2] (Default: 1): " scope_choice
    scope_choice=$(echo "$scope_choice" | tr -d ' ')

    local scope="global"
    if [ "$scope_choice" = "2" ]; then
        scope="folder"
    fi

    # Mode
    echo ""
    echo -e "${BOLD}Select cleanup mode:${NC}"
    echo "  1) Safe Mode: Strip numbers + Move duplicates to .duplicates_trash [Default]"
    echo "  2) Permanent Mode: Strip numbers + Permanently delete duplicates"
    echo "  3) Dry Run: Preview changes without modifying any files"
    read -r -p "Choice [1-3] (Default: 1): " mode_choice
    mode_choice=$(echo "$mode_choice" | tr -d ' ')

    local cmd_args=("$CLEANER_SCRIPT" "--target" "$target_dir" "--scope" "$scope")

    case "$mode_choice" in
        2) cmd_args+=("--permanent-delete") ;;
        3) cmd_args+=("--dry-run") ;;
        *) ;;
    esac

    echo ""
    echo -e "${BLUE}${BOLD}--- Execution Plan ---${NC}"
    echo -e "  ${BOLD}Target:${NC} $target_dir"
    echo -e "  ${BOLD}Scope:${NC}  $scope"
    if [ "$mode_choice" = "3" ]; then
        echo -e "  ${BOLD}Mode:${NC}   Dry Run (Simulation only)"
    elif [ "$mode_choice" = "2" ]; then
        echo -e "  ${BOLD}Mode:${NC}   Permanent Delete Duplicates"
    else
        echo -e "  ${BOLD}Mode:${NC}   Move Duplicates to .duplicates_trash (Safe)"
    fi
    echo -e "${BLUE}----------------------${NC}\n"

    "$PYTHON_BIN" "${cmd_args[@]}"

    echo ""
    read -r -p "Press Enter to return to main menu..." dummy
}

# ------------------------------------------------------------------------------
# 7. Media Player Flow (with Shuffle Option)
# ------------------------------------------------------------------------------
player_flow() {
    print_header

    # Check if player daemon is already running in background
    local player_status
    player_status=$("$PYTHON_BIN" "$PLAYER_SCRIPT" --status 2>/dev/null || echo "STOPPED")

    if [ "$player_status" != "STOPPED" ]; then
        # Already running! Connect directly without asking questions or restarting!
        "$PYTHON_BIN" "$PLAYER_SCRIPT"
        return 0
    fi

    echo -e "${GREEN}${BOLD}--- Music & Media Player ---${NC}\n"

    # Check if any audio/media files exist in downloads
    local track_count
    track_count=$(find "$SCRIPT_DIR/downloads" -type f \( -name "*.mp3" -o -name "*.m4a" -o -name "*.flac" -o -name "*.wav" -o -name "*.aac" -o -name "*.opus" -o -name "*.ogg" -o -name "*.mp4" \) 2>/dev/null | grep -v "/\.duplicates_trash/" | wc -l | tr -d ' ')

    if [ -z "$track_count" ] || [ "$track_count" -eq 0 ]; then
        echo -e "${YELLOW}[!] No downloaded media files found in: $SCRIPT_DIR/downloads${NC}"
        echo -e "Please download some tracks first from YouTube or Spotify!\n"
        read -r -p "Press Enter to return to main menu..." dummy
        return 0
    fi

    echo -e "Found ${BOLD}$track_count${NC} downloaded track(s).\n"

    # Select folder or playlist
    echo -e "${BOLD}Select playlist or folder to play:${NC}"
    echo "  1) All downloads (downloads/) [Default]"
    echo "  2) Liked / Favorite Tracks (❤️ Likes)"
    echo "  3) MP3 only (downloads/mp3/)"
    echo "  4) Spotify only (downloads/spotify/)"
    echo "  5) MP4 only (downloads/mp4/)"
    echo "  6) Custom folder"
    read -r -p "Choice [1-6] (Default: 1): " folder_choice
    folder_choice=$(echo "$folder_choice" | tr -d ' ')

    local play_dir="$SCRIPT_DIR/downloads"
    local fav_flag=""
    case "$folder_choice" in
        2)
            fav_flag="--favorites"
            ;;
        3) play_dir="$SCRIPT_DIR/downloads/mp3" ;;
        4) play_dir="$SCRIPT_DIR/downloads/spotify" ;;
        5) play_dir="$SCRIPT_DIR/downloads/mp4" ;;
        6)
            read -r -p "Enter custom folder path: " custom_path
            play_dir="$custom_path"
            ;;
        *) play_dir="$SCRIPT_DIR/downloads" ;;
    esac

    # Shuffle option
    echo ""
    read -r -p "Enable Shuffle mode? (Y/n, Default: Y): " shuffle_choice
    shuffle_choice=$(echo "$shuffle_choice" | tr -d ' ')

    local cmd_args=("$play_dir")
    if [ -n "$fav_flag" ]; then
        cmd_args+=("$fav_flag")
    fi
    if [[ ! "$shuffle_choice" =~ ^[nN]([oO])?$ ]]; then
        cmd_args+=("--shuffle")
    fi

    echo -e "\n${CYAN}[*] Starting player...${NC}"
    "$PYTHON_BIN" "$PLAYER_SCRIPT" "${cmd_args[@]}"
}

# ------------------------------------------------------------------------------
# 8. Main Interactive Menu
# ------------------------------------------------------------------------------
main_menu() {
    while true; do
        print_header

        local player_status
        player_status=$("$PYTHON_BIN" "$PLAYER_SCRIPT" --status 2>/dev/null || echo "STOPPED")

        local player_label="Play Downloaded Music (with Shuffle Option)"
        if [[ "$player_status" =~ ^PLAYING:(.+) ]]; then
            local curr_title="${player_status#PLAYING:}"
            if [ ${#curr_title} -gt 28 ]; then
                curr_title="${curr_title:0:25}..."
            fi
            player_label="Back to Player (▶ Playing: ${curr_title})"
        elif [[ "$player_status" =~ ^PAUSED:(.+) ]]; then
            local curr_title="${player_status#PAUSED:}"
            if [ ${#curr_title} -gt 28 ]; then
                curr_title="${curr_title:0:25}..."
            fi
            player_label="Back to Player (⏸ Paused: ${curr_title})"
        fi

        echo -e "${BOLD}What would you like to do?${NC}\n"
        echo "  1) Search YouTube & Download (Top 15 Results) [Default]"
        echo "  2) Download from URL (YouTube or Spotify)"
        echo "  3) $player_label"
        echo "  4) Clean Filenames & Remove Duplicates"
        echo "  5) Exit"
        echo ""
        read -r -p "Select option [1-5] (Default: 1): " menu_choice
        menu_choice=$(echo "$menu_choice" | tr -d ' ')

        case "$menu_choice" in
            1|"")
                search_youtube_flow
                ;;
            2)
                download_flow
                ;;
            3)
                player_flow
                ;;
            4)
                cleanup_flow
                ;;
            5|"q"|"quit"|"exit")
                if [ "$player_status" != "STOPPED" ]; then
                    echo ""
                    echo -e "${YELLOW}[!] Music is still playing in the background.${NC}"
                    read -r -p "Stop player before exiting? (Y/n, Default: Y): " stop_choice
                    if [[ ! "$stop_choice" =~ ^[nN]([oO])?$ ]]; then
                        "$PYTHON_BIN" "$PLAYER_SCRIPT" --stop &>/dev/null || true
                        echo -e "${GREEN}[✓] Player stopped.${NC}"
                    fi
                fi
                echo -e "${GREEN}Goodbye!${NC}"
                exit 0
                ;;
            *)
                echo -e "${YELLOW}[!] Invalid option. Please select 1-5.${NC}"
                sleep 1
                ;;
        esac
    done
}

# ------------------------------------------------------------------------------
# 9. Entrypoint
# ------------------------------------------------------------------------------
init_environment

if [ $# -gt 0 ]; then
    # Direct CLI argument pass-through
    if [ "$1" = "--clean" ]; then
        shift
        "$PYTHON_BIN" "$CLEANER_SCRIPT" "$@"
    elif [ "$1" = "--play" ] || [ "$1" = "--player" ] || [ "$1" = "-p" ]; then
        shift
        "$PYTHON_BIN" "$PLAYER_SCRIPT" "$@"
    elif [ "$1" = "--search" ] || [ "$1" = "-s" ]; then
        "$PYTHON_BIN" "$YOUTUBE_SCRIPT" "$@"
    elif echo "$1" | grep -qE "spotify\.com|spotify\.link"; then
        "$PYTHON_BIN" "$SPOTIFY_SCRIPT" "$@"
    else
        "$PYTHON_BIN" "$YOUTUBE_SCRIPT" "$@"
    fi
else
    # Launch main menu
    main_menu
fi
