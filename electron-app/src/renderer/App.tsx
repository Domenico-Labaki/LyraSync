import React, { useEffect, useRef, useState } from 'react';
import { PlaybackWithLyrics } from '../main/PlaybackState';
import { getAccentColor, soften, isColorDark, lightenColor, hexToRGB, colors } from './theme/colors';
import { SyncedLyrics } from './components/SyncedLyrics';
import { LoginScreen } from './components/LoginScreen';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEye, faArrowRightFromBracket, faClose } from '@fortawesome/free-solid-svg-icons'
import { ScrollingText } from './components/ScrollingText';
import type { ModelProgressEvent } from "../main/modelManager";

type AuthStatus = {
  authenticated: boolean;
  source: 'spotify' | 'guest' | null;
};

interface AlignSentence {
  line:       string;
  start:      number;   // seconds
  end:        number;   // seconds
  confidence: number;
}

declare global {
  interface Window {
    api: {
      onPlaybackStateChanged: (callback: (state: PlaybackWithLyrics | null) => void) => void;
      onHoverChanged: (callback: (hovered: boolean) => void) => void;
      onAuthStatus: (callback: (status: AuthStatus) => void) => void;
      startSpotifyLogin: () => void;
      startGuestMode: () => void;
      startLogin: () => void;
      rendererReady: () => void;
      setFocusMode: (enabled: boolean) => void;
      logout: () => void;
      closeApp: () => void;
      onProgress: (cb: (event: ModelProgressEvent) => void) => void;
      onReady: (cb: () => void) => void;
      removeAllListeners: () => void;
      alignTrack: (params: {
        title:       string;
        artist:      string;
        durationSec: number | null;
        lyrics:      string;
        trackId:     string;
      }) => Promise<{
        sentences:     AlignSentence[];
        used_fallback: boolean;
        duration_sec:  number;
        cached:        boolean;
      }>;
    };
  }
}

// ── Convert alignment sentences → LRC string ──────────────────────────────────
//
// SyncedLyrics already knows how to parse LRC format, so we convert the
// alignment result into the same format it already expects rather than
// changing SyncedLyrics itself.
//
// Output format: "[MM:SS.mm] Line text\n"
// Example:       "[00:16.71] Just 'cause you grow\n"

function sentencesToLrc(sentences: AlignSentence[]): string {
  return sentences
    .map(({ line, start }) => {
      const totalMs  = Math.round(start * 1000);
      const minutes  = Math.floor(totalMs / 60_000);
      const seconds  = Math.floor((totalMs % 60_000) / 1000);
      const centis   = Math.floor((totalMs % 1000) / 10);
      const mm  = String(minutes).padStart(2, "0");
      const ss  = String(seconds).padStart(2, "0");
      const cc  = String(centis).padStart(2, "0");
      return `[${mm}:${ss}.${cc}] ${line}`;
    })
    .join("\n");
}

export default function App() {
  const [playbackState, setPlaybackState] = useState<PlaybackWithLyrics | null>(null);
  const [bg, setBg] = useState<string>('');
  const [accent, setAccent] = useState(hexToRGB(colors.background.primary));
  const [oldTrackId, setOldTrackId] = useState<string | null>(null);
  const [coverUrl, setCoverUrl] = useState<string>('');
  const [focusMode, setFocusMode] = useState<boolean>(false);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [displayProgress, setDisplayProgress] = useState(0);
  const [lastSync, setLastSync] = useState(0);

  // ── Alignment state ───────────────────────────────────────────────────────
  // alignedLrc holds the LRC string produced from a successful alignment.
  // alignState tracks the lifecycle so renderLyrics() knows what to show.
  const [alignedLrc, setAlignedLrc]   = useState<string | null>(null);
  const [alignState, setAlignState]   = useState<"idle" | "loading" | "done" | "error">("idle");
  const aligningForTrack = useRef<string | null>(null);   // prevents duplicate calls

  // Update playback state
  useEffect(() => {
    window.api.onPlaybackStateChanged((state) => {
      console.log('Playback state received:', state);
      if (!state) {
        setPlaybackState(null);
        setAuthStatus({ authenticated: false, source: null });
        return;
      }

      setPlaybackState(prev => ({
        ...prev,
        ...state,
        lyrics: (state as any).lyrics ?? prev?.lyrics ?? null
      }));
      setAuthStatus(prev => prev ? { ...prev, authenticated: true } : prev);
    });

    window.api.rendererReady?.();
    window.api.onAuthStatus?.((s) => setAuthStatus(s));
  }, []);

  const displaySong   = playbackState ? playbackState.trackName : '-';
  const displayArtist = playbackState ? playbackState.artist    : '-';

  const plainLyricsRef = useRef<HTMLDivElement>(null);

  // Reset alignment state when track changes
  useEffect(() => {
    if (!oldTrackId || playbackState?.trackId !== oldTrackId) {
      setPlaybackState(prev => prev ? { ...prev, lyrics: null } : null);
      setAlignedLrc(null);
      setAlignState("idle");
      aligningForTrack.current = null;

      if (plainLyricsRef.current) {
        plainLyricsRef.current.scrollTop = 0;
      }
      if (playbackState?.trackId) {
        setOldTrackId(playbackState.trackId);
      }
      setCoverUrl('');
    }
  }, [playbackState?.trackId, playbackState?.imgUrl]);

  // ── Trigger alignment when plain-only lyrics arrive ───────────────────────
  //
  // Conditions to call /align:
  //   - We have plain lyrics but no synced lyrics
  //   - We haven't already started aligning this track (aligningForTrack guard)
  //   - The track has a valid trackId, title, and artist
  //
  useEffect(() => {
    const lyrics  = playbackState?.lyrics;
    const trackId = playbackState?.trackId;
    const title   = playbackState?.trackName;
    const artist  = playbackState?.artist;

    const shouldAlign =
      lyrics?.plain &&
      lyrics?.plain != 'No lyrics found' &&
      !lyrics?.synced &&
      trackId &&
      title &&
      artist &&
      aligningForTrack.current !== trackId &&
      alignState === "idle";

    if (!shouldAlign) return;

    aligningForTrack.current = trackId!;
    setAlignState("loading");

    const durationSec = playbackState?.durationMs
      ? Math.round(playbackState.durationMs / 1000)
      : null;

    window.api.alignTrack({
      title:       title!,
      artist:      artist!,
      durationSec,
      lyrics:      lyrics!.plain,
      trackId:     trackId!,
    })
      .then((result) => {
        // Guard: user may have changed track while alignment was running
        if (aligningForTrack.current !== trackId) return;

        const lrc = sentencesToLrc(result.sentences);
        setAlignedLrc(lrc);
        setAlignState("done");
        console.log(
          `[align] ${result.sentences.length} lines | ` +
          `cached=${result.cached} | fallback=${result.used_fallback}`
        );
      })
      .catch((err: Error) => {
        if (aligningForTrack.current !== trackId) return;
        console.error("[align] failed:", err.message);
        setAlignState("error");
      });
  }, [playbackState?.lyrics, playbackState?.trackId, alignState]);

  // Detect cover URL changes and update accent color
  useEffect(() => {
    if (!coverUrl || playbackState?.imgUrl !== coverUrl) {
      const newCoverUrl = playbackState?.imgUrl ? playbackState.imgUrl : '';
      console.log('Setting coverUrl to:', newCoverUrl);
      setCoverUrl(newCoverUrl);
    }
  }, [playbackState?.imgUrl]);

  // Update background color when cover URL changes
  useEffect(() => {
    console.log('Cover URL changed:', coverUrl);
    if (coverUrl) {
      getAccentColor(coverUrl).then((accentColor: string) => {
        setAccent(accentColor);
        const newBg = `linear-gradient(180deg, ${soften(accentColor)}, #212121)`;
        setBg(newBg);
      });
    }
  }, [coverUrl]);

  // Update progress
  useEffect(() => {
    if (playbackState?.progressMs != null) {
      setLastSync(Date.now());
    }
  }, [playbackState?.progressMs]);

  useEffect(() => {
    let raf: number;
    const loop = () => {
      const now   = Date.now();
      const delta = playbackState?.isPlaying ? now - lastSync : 0;
      setDisplayProgress((playbackState?.progressMs ?? 0) + delta);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playbackState?.progressMs, playbackState?.isPlaying, lastSync]);

  // Hover states
  const [isHovered, setIsHovered] = useState(false);
  useEffect(() => {
    window.api.onHoverChanged(setIsHovered);
  }, []);

  // ── Render lyrics ─────────────────────────────────────────────────────────
  function renderLyrics() {
    if (!playbackState) return <div className="loader" />;
    if (!playbackState.lyrics) return <div className="loader" />;

    // Synced lyrics from LRCLIB — fastest path, no alignment needed
    if (playbackState.lyrics.synced) {
      return (
        <SyncedLyrics
          lyricsRaw={playbackState.lyrics.synced}
          progressMs={displayProgress}
        />
      );
    }

    // Plain lyrics — show alignment result if ready, loader while waiting,
    // static plain text if alignment failed
    if (playbackState.lyrics.plain) {

      if (alignState === "done" && alignedLrc) {
        return (
          <SyncedLyrics
            lyricsRaw={alignedLrc}
            progressMs={displayProgress}
          />
        );
      }

      if (alignState === "loading") {
        // Show static plain text behind a subtle indicator while aligning.
        // Once done, SyncedLyrics replaces it seamlessly.
        return (
          <div
            ref={plainLyricsRef}
            style={{ ...plainLyrics, color: focusMode ? 'white' : colors.text.primary }}
          >
            {playbackState.lyrics.plain}
          </div>
        );
      }

      // alignState === "error" or "idle" — show plain text as fallback
      return (
        <div
          ref={plainLyricsRef}
          style={{ ...plainLyrics, color: focusMode ? 'white' : colors.text.primary }}
        >
          {playbackState.lyrics.plain}
        </div>
      );
    }

    return <div className="loader" />;
  }

  function toggleFocusMode() {
    const newVal = !focusMode;
    setFocusMode(newVal);
    window.api.setFocusMode?.(newVal);
  }

  function logOut() {
    window.api.logout?.();
    setAuthStatus({ authenticated: false, source: null });
    setPlaybackState(null);
    setCoverUrl('');
    setOldTrackId(null);
    setBg('');
    setAccent(hexToRGB(colors.primary.spotify));
    setFocusMode(false);
    setAlignedLrc(null);
    setAlignState("idle");
    aligningForTrack.current = null;
  }

  function exit() {
    window.api.closeApp();
  }

  useEffect(() => {
    window.api.setFocusMode?.(focusMode);
  }, []);

  if (authStatus === null) {
    return (
      <div className="dragBar" style={{ ...container, backgroundColor: '#1B1C1F', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ color: colors.text.primary }}>Loading session...</div>
      </div>
    );
  }

  if (!authStatus.authenticated) {
    return (
      <LoginScreen
        onSpotifyLogin={() => window.api.startSpotifyLogin?.()}
        onGuestMode={() => window.api.startGuestMode?.()}
      />
    );
  }

  return (
    <div
      style={{
        ...container,
        opacity: focusMode ? 0.75 : 1,
        transition: "opacity 0.15s ease"
      }}
    >
      <div style={{
        ...lyricsContainer,
        backgroundImage: focusMode ? undefined : (bg || undefined),
        backgroundColor:  focusMode ? undefined : (!bg ? accent : undefined),
        pointerEvents:    focusMode ? 'none' : 'auto',
        WebkitTextStroke: focusMode ? '3px rgba(0,0,0,0.3)' : '0px'
      }}>
        <img
          style={{ ...coverImage, visibility: focusMode ? 'hidden' : 'visible', borderColor: isColorDark(accent) ? lightenColor(accent) : accent }}
          src={coverUrl}
        />
        {renderLyrics()}
      </div>
      <div className="dragBar" style={songBar}>
        <div style={{ ...songTitleContainer, color: isColorDark(accent) ? lightenColor(accent) : accent }}>
          <ScrollingText text={displaySong} />
        </div>
        <div style={artistNameContainer}>
          <ScrollingText text={displayArtist} />
        </div>
        <button className={focusMode ? "pressed iconButton" : "iconButton"} onClick={toggleFocusMode} aria-label="Toggle focus">
          <FontAwesomeIcon icon={faEye} />
        </button>
        <button className="iconButton" style={{ pointerEvents: focusMode ? 'none' : 'auto', opacity: focusMode ? 0.5 : 1 }} onClick={logOut} aria-label="Log out">
          <FontAwesomeIcon icon={faArrowRightFromBracket} />
        </button>
        <button className="iconButton" onClick={exit} aria-label="Exit">
          <FontAwesomeIcon icon={faClose} />
        </button>
      </div>
    </div>
  );
}

const container: React.CSSProperties = {
  width: '100%',
  height: '100vh',
  maxWidth: '100%',
  background: 'transparent',
  pointerEvents: 'auto',
  transition: 'opacity 0.1s ease',
  display: 'flex',
  flexDirection: 'column',
};

const lyricsContainer: React.CSSProperties = {
  position: 'relative',
  width: '100%',
  height: '88%',
  borderTopLeftRadius: 8,
  borderTopRightRadius: 8,
  paddingLeft: 20,
  paddingRight: 30,
  paddingTop: 20,
  overflow: 'hidden',
  boxSizing: 'border-box',
  pointerEvents: 'inherit',
  paintOrder: 'stroke fill'
};

const plainLyrics: React.CSSProperties = {
  width: '100%',
  height: '100%',
  display: 'flex',
  flexWrap: 'wrap',
  whiteSpace: 'pre-wrap',
  lineHeight: 2,
  fontSize: '25px',
  textShadow: '0 2px 8px rgba(0,0,0,0.5)',
  overflowY: 'auto',
  fontWeight: 800,
  pointerEvents: 'inherit',
  userSelect: 'none',
  transition: "color 0.15s ease"
};

const coverImage: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  height: '88%',
  zIndex: 1,
  filter: 'blur(3px)',
  borderTopLeftRadius: 8,
  maskImage: 'linear-gradient(to right, black 30%, transparent 100%)',
  opacity: 0.5,
  pointerEvents: 'none',
};

const songBar: React.CSSProperties = {
  width: '100%',
  height: '10%',
  boxSizing: 'border-box',
  backgroundColor: colors.background.secondary,
  display: 'flex',
  flexDirection: 'row',
  alignItems: 'center',
  borderBottomLeftRadius: 8,
  borderBottomRightRadius: 8,
  userSelect: 'none',
  paddingRight: 10,
  paddingLeft: 10
};

const songTitleContainer: React.CSSProperties = {
  color: colors.text.accent,
  fontSize: '15px',
  paddingRight: 10,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  maxWidth: '60%',
};

const artistNameContainer: React.CSSProperties = {
  color: colors.text.primary,
  fontSize: '15px',
  paddingRight: 5,
  flex: 1,
  whiteSpace: 'nowrap',
  overflow: 'hidden'
};