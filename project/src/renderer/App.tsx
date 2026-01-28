import React, { useEffect, useRef, useState } from 'react';
import { PlaybackWithLyrics } from '../main/PlaybackState';
import { getAccentColor, soften, isColorDark, lightenColor, hexToRGB, colors } from './theme/colors';

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
  const [accent, setAccent] = useState(hexToRGB(colors.primary.spotify));
  const [oldTrackId, setOldTrackId] = useState<string | null>(null);
  const [coverUrl, setCoverUrl] = useState<string>('');
  const [focusMode, setFocusMode] = useState<boolean>(false);
  const [authStatus, setAuthStatus] = useState<boolean | null>(null); // null = checking

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

  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    window.api.onHoverChanged(setIsHovered);
  }, []);

  function renderLyrics() {
    if (!playbackState?.lyrics) {
      return <div>Lyrics unavailable for this song</div>;
    }

    // if (playbackState.lyrics.synced) {
    //   return(
    //     <div>
    //       Synced lyrics are available
    //     </div>
    //   );
    // }

    if (playbackState.lyrics.plain) {
      return (
        <div ref={plainLyricsRef} style={{...plainLyrics, color: focusMode? 'white': colors.text.primary}}>
          {playbackState.lyrics.plain}
        </div>
      );
    }

    return <div>Lyrics unavailable for this song</div>;
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

  useEffect(() => {
    // Ensure main process knows the initial focusMode
    window.api.setFocusMode?.(focusMode);
  }, []);

  // Auth UI: show loader / login button if not authenticated
  if (authStatus === null) {
    return (
      <div style={{...container, backgroundColor: colors.background.primary, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <div style={{color: colors.text.primary}}>Loading session...</div>
      </div>
    );
  }

  if (authStatus === false) {
    return (
      <div style={{...container, backgroundColor: colors.background.primary, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <div style={{textAlign: 'center'}}>
          <div style={{color: colors.text.primary, marginBottom: 12}}>Not signed in</div>
          <button onClick={() => window.api.startLogin?.()}>Sign in with Spotify</button>
        </div>
      </div>
    );
  }

  // Authenticated: render main UI
  return (
    <div
    style={{
      ...container,
      //opacity: isHovered ? 0.4 : 0.85,
      opacity: focusMode ? 0.3 : 1,
      transition: "opacity 0.15s ease"
    }}
    >
      <div style={{
          ...lyricsContainer,
          backgroundImage: bg || undefined,
          backgroundColor: !bg ? accent : undefined,
          pointerEvents: focusMode ? 'none' : 'auto'
        }}>
        <img style={coverImage} src={coverUrl}></img>
        {renderLyrics()}
      </div>
      <div style={songBar}>
        <div style={{...songTitleContainer, color: isColorDark(accent) ? lightenColor(accent): accent}}>{displaySong}</div>
        <div style={artistNameContainer}>{displayArtist}</div>
        <button className={focusMode ? "pressed iconButton" : "iconButton"} onClick={toggleFocusMode}>Focus</button>
        <button className="iconButton" onClick={logOut}>Log Out</button>
      </div>
    </div>
  );
}

const container: React.CSSProperties = {
  width: '100vw',
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
  height: '90%',
  borderTopLeftRadius: 8,
  borderTopRightRadius: 8,
  paddingLeft: 20,
  paddingRight: 20,
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
  position: 'absolute',
  inset: 0,
  height: '100%',
  zIndex: 0,
  filter: 'blur(3px)',
  maskImage: 'linear-gradient(to right, black 30%, transparent 100%)',
  opacity: 0.5,
  pointerEvents: 'none'
};

const songBar: React.CSSProperties = {
  width: '100%',
  height: '10%',
  backgroundColor: colors.background.secondary,
  display: 'flex',
  flexDirection: 'row',
  alignItems: 'center',
  borderBottomLeftRadius: 8,
  borderBottomRightRadius: 8,
  userSelect: 'none'
};

const songTitleContainer: React.CSSProperties = {
  color: colors.text.accent,
  fontSize: '15px',
  paddingLeft: 10,
  paddingRight: 5
};

const artistNameContainer: React.CSSProperties = {
  color: colors.text.primary,
  fontSize: '15px',
  paddingLeft: 5,
  paddingRight: 5
};
