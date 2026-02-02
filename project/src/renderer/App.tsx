import React, { useEffect, useRef, useState } from 'react';
import { PlaybackWithLyrics } from '../main/PlaybackState';
import { getAccentColor, soften, isColorDark, lightenColor, hexToRGB, colors } from './theme/colors';
import { SyncedLyrics } from './components/SyncedLyrics';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEye, faArrowRightFromBracket, faClose } from '@fortawesome/free-solid-svg-icons'
import { ScrollingText } from './components/ScrollingText';
import brandLogo from '../imgs/logo.png';

declare global {
  interface Window {
    api: {
      onPlaybackStateChanged: (callback: (state: PlaybackWithLyrics | null) => void) => void;
      onHoverChanged: (callback: (hovered: boolean) => void) => void;
      onAuthStatus: (callback: (status: boolean) => void) => void;
      startLogin: () => void;
      rendererReady: () => void;
      setFocusMode: ((enabled: boolean) => void);
      logout: (() => void);
    };
  }
}

export default function App() {
  const [playbackState, setPlaybackState] = useState<PlaybackWithLyrics | null>(null);
  const [bg, setBg] = useState<string>('');
  const [accent, setAccent] = useState(hexToRGB(colors.background.primary));
  const [oldTrackId, setOldTrackId] = useState<string | null>(null);
  const [coverUrl, setCoverUrl] = useState<string>('');
  const [focusMode, setFocusMode] = useState<boolean>(false);
  const [authStatus, setAuthStatus] = useState<boolean | null>(null); // null = checking
  const [displayProgress, setDisplayProgress] = useState(0);
  const [lastSync, setLastSync] = useState(0);
  const baseProgressRef = useRef(0);

  // Update playback state
  useEffect(() => {
    window.api.onPlaybackStateChanged((state) => {
      if (!state) {
        setPlaybackState(null);
        setAuthStatus(false);
        return;
      }

      setPlaybackState(prev => ({
        ...prev,
        ...state,
        lyrics: (state as any).lyrics ?? prev?.lyrics ?? null
      }));
      setAuthStatus(true);
    });

    window.api.rendererReady?.();
    window.api.onAuthStatus?.((s) => setAuthStatus(!!s));
  }, []);

  const displaySong = playbackState
    ? `${playbackState.trackName}`
    : '-';
  
  const displayArtist = playbackState
    ? `${playbackState.artist}`
    : '-';

  const plainLyricsRef = useRef<HTMLDivElement>(null);
  // Update cover URL when track changes
  useEffect(() => {
    if (!oldTrackId || playbackState?.trackId !== oldTrackId) {
      // Clear lyrics when track changes
      setPlaybackState(prev => prev ? { ...prev, lyrics: null } : null);

      if (plainLyricsRef.current) { // There currently exists plain lyrics container
        plainLyricsRef.current.scrollTop = 0;
      }
      setCoverUrl(playbackState?.imgUrl ? playbackState.imgUrl : '');
      if (playbackState?.trackId) {
        setOldTrackId(playbackState.trackId);
      }
    }
  }, [playbackState?.trackId, playbackState?.imgUrl, oldTrackId]);

  // Update background color when cover URL changes
  useEffect(() => {
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
      const now = Date.now();
      const delta = playbackState?.isPlaying ? now - lastSync : 0;
      setDisplayProgress((playbackState?.progressMs ? playbackState.progressMs : 0) + delta);
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

  function renderLyrics() {
    if (!playbackState) {
      return <div className="loader"></div>;
    }
    if (!playbackState.lyrics) {
      return <div className="loader"></div>;
    }

    if (playbackState.lyrics.synced) {
      return(
        <SyncedLyrics
          lyricsRaw={playbackState.lyrics.synced}
          progressMs={displayProgress}
        />
      );
    }

    if (playbackState.lyrics.plain) {
      return (
        <div ref={plainLyricsRef} style={{...plainLyrics, color: focusMode? 'white': colors.text.primary}}>
          {playbackState.lyrics.plain}
        </div>
      );
    }

    return <div className="loader"></div>;
  }

  function toggleFocusMode() {
    const newVal = !focusMode;
    setFocusMode(newVal);
    window.api.setFocusMode?.(newVal);
  }

  function logOut() {
    // Notify main process to clear stored tokens
    window.api.logout?.();

    setAuthStatus(false);

    // Clear UI and playback state
    setPlaybackState(null);
    setCoverUrl('');
    setOldTrackId(null);
    setBg('');
    setAccent(hexToRGB(colors.primary.spotify));
    setFocusMode(false);
  }

  // Exit the Electron window
  function exit() {
    window.close();
  }

  useEffect(() => {
    // Ensure main process knows the initial focusMode
    window.api.setFocusMode?.(focusMode);
  }, []);

  // Auth UI: show loader / login button if not authenticated
  if (authStatus === null) {
    return (
      <div className="dragBar" style={{...container, backgroundColor: '#1B1C1F', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <div style={{color: colors.text.primary}}>Loading session...</div>
      </div>
    );
  }

  if (authStatus === false) {
    return (
      <div className="dragBar" style={{...container, backgroundColor: '#1B1C1F', display: 'flex', alignItems: 'center', justifyContent: 'space-around', paddingTop: '10px', paddingBottom: '10px'}}>
        <div style={{textAlign: 'center'}}>
          <img src={brandLogo} width="125px"></img>
          <div style={{color: colors.text.primary, marginBottom: 12, marginTop: 25}}>Not signed in</div>
          <button onClick={() => window.api.startLogin?.()}>Sign in with Spotify</button>
        </div>
        <div style={{color: colors.text.primary, fontSize: '12px'}}>© 2026 Domenico Labaki</div>
      </div>
    );
  }

  // Authenticated: render main UI
  return (
    <div
    style={{
      ...container,
      //opacity: isHovered ? 0.4 : 0.85,
      opacity: focusMode ? 0.75 : 1,
      transition: "opacity 0.15s ease"
    }}
    >
      <div style={{
          ...lyricsContainer,
          backgroundImage: focusMode ? undefined : (bg || undefined),
          backgroundColor: focusMode ? undefined: (!bg ? accent : undefined),
          pointerEvents: focusMode ? 'none' : 'auto'
        }}>
        <img style={{...coverImage, visibility: focusMode ? 'hidden' : 'visible', borderColor: isColorDark(accent) ? lightenColor(accent): accent}} src={coverUrl}></img>
        {renderLyrics()}
      </div>
      <div className="dragBar" style={songBar}>
        <div style={{...songTitleContainer, color: isColorDark(accent) ? lightenColor(accent): accent}}>
          <ScrollingText text={displaySong} />
        </div>
        <div style={artistNameContainer}>
          <ScrollingText text={displayArtist} />
        </div>
        <button className={focusMode ? "pressed iconButton" : "iconButton"} onClick={toggleFocusMode} aria-label="Toggle focus">
          <FontAwesomeIcon icon={faEye} />
        </button>
        <button className="iconButton" style={{pointerEvents: focusMode ? 'none' : 'auto', opacity: focusMode ? 0.5 : 1}} onClick={logOut} aria-label="Log out">
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
  // Padding is taken into consideration for width calculation (child can have 100% width and not go over padding zone)
  boxSizing: 'border-box',
  pointerEvents: 'inherit'
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
}

const coverImage: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  height: '88%',
  zIndex: 1,
  filter: 'blur(3px)',
  borderTopLeftRadius: 8,
  // padding: '2px',
  // borderWidth: '2px',
  // borderStyle: 'solid',
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
