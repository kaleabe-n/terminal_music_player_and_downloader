import Foundation
import MediaPlayer
import AppKit

// Keep stdout unbuffered
setbuf(stdout, nil)

class MediaKeyManager {
    static let shared = MediaKeyManager()
    let commandCenter = MPRemoteCommandCenter.shared()
    let nowPlayingInfoCenter = MPNowPlayingInfoCenter.default()
    var monitors: [Any] = []

    func setup() {
        // 1. MPRemoteCommandCenter (Controls from OS, Control Center, Touch Bar, Bluetooth)
        commandCenter.togglePlayPauseCommand.isEnabled = true
        commandCenter.togglePlayPauseCommand.addTarget { [weak self] _ in
            self?.notify("TOGGLE_PLAY_PAUSE")
            return .success
        }

        commandCenter.playCommand.isEnabled = true
        commandCenter.playCommand.addTarget { [weak self] _ in
            self?.notify("PLAY")
            return .success
        }

        commandCenter.pauseCommand.isEnabled = true
        commandCenter.pauseCommand.addTarget { [weak self] _ in
            self?.notify("PAUSE")
            return .success
        }

        commandCenter.nextTrackCommand.isEnabled = true
        commandCenter.nextTrackCommand.addTarget { [weak self] _ in
            self?.notify("NEXT")
            return .success
        }

        commandCenter.previousTrackCommand.isEnabled = true
        commandCenter.previousTrackCommand.addTarget { [weak self] _ in
            self?.notify("PREV")
            return .success
        }

        // 2. Local & Global Event Monitors for Hardware Media Keys
        let handleEvent: (NSEvent) -> Void = { [weak self] event in
            guard event.type == .systemDefined, event.subtype.rawValue == 8 else { return }
            let keyCode = ((event.data1 & 0xFFFF0000) >> 16)
            let keyFlags = (event.data1 & 0x0000FFFF)
            let keyState = (((keyFlags & 0xFF00) >> 8)) == 0xA // 0xA is key down, 0xB is key up

            if keyState {
                switch keyCode {
                case 16: // NX_KEYTYPE_PLAY / PAUSE
                    self?.notify("TOGGLE_PLAY_PAUSE")
                case 19: // NX_KEYTYPE_NEXT / FAST
                    self?.notify("NEXT")
                case 20: // NX_KEYTYPE_PREVIOUS / REWIND
                    self?.notify("PREV")
                default:
                    break
                }
            }
        }

        if let localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.systemDefined], handler: { event in
            handleEvent(event)
            return event
        }) {
            monitors.append(localMonitor)
        }

        if let globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.systemDefined], handler: handleEvent) {
            monitors.append(globalMonitor)
        }

        // 3. Background thread to listen to stdin for metadata updates from player.py
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            while let line = readLine() {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.hasPrefix("NOW_PLAYING:") {
                    let payload = String(trimmed.dropFirst("NOW_PLAYING:".count))
                    let parts = payload.components(separatedBy: "|")
                    let title = parts.count > 0 ? parts[0] : "Media Player"
                    let artist = parts.count > 1 ? parts[1] : ""
                    let isPlaying = parts.count > 2 ? (parts[2] == "PLAYING") : true
                    self?.updateNowPlaying(title: title, artist: artist, isPlaying: isPlaying)
                } else if trimmed == "QUIT" {
                    exit(0)
                }
            }
        }

        print("LISTENER_READY")
        fflush(stdout)
    }

    func notify(_ command: String) {
        print(command)
        fflush(stdout)
    }

    func updateNowPlaying(title: String, artist: String, isPlaying: Bool) {
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: title,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0
        ]
        if !artist.isEmpty {
            info[MPMediaItemPropertyArtist] = artist
        }
        nowPlayingInfoCenter.nowPlayingInfo = info
        if #available(macOS 10.13, *) {
            nowPlayingInfoCenter.playbackState = isPlaying ? .playing : .paused
        }
    }
}

MediaKeyManager.shared.setup()
RunLoop.main.run()
