import React, { useEffect, useState } from 'react';
import { PlaybackWithLyrics } from '../main/PlaybackState';
import { getAccentColor, soften, isColorDark, lightenColor, hexToRGB, colors } from './theme/colors';

declare global {
  interface Window {
    api: {
      onPlaybackStateChanged: (callback: (state: PlaybackWithLyrics) => void) => void;
      onHoverChanged: (callback: (hovered: boolean) => void) => void;
    };
  }
}

export default function App() {
  const [playbackState, setPlaybackState] = useState<PlaybackWithLyrics | null>(null);
  const [bg, setBg] = useState<string>('');
  const [accent, setAccent] = useState(hexToRGB(colors.primary.spotify));
  const [oldTrackId, setOldTrackId] = useState<string | null>(null);
  const [coverUrl, setCoverUrl] = useState<string>('');

  useEffect(() => {
    window.api.onPlaybackStateChanged((state) => {
      setPlaybackState(prev => ({
        ...prev,
        ...state,
        lyrics: state.lyrics ?? prev?.lyrics ?? null
      }));
    });
  }, []);

  const displaySong = playbackState
    ? `${playbackState.trackName}`
    : '-';
  
  const displayArtist = playbackState
    ? `${playbackState.artist}`
    : '-';

  // Update cover URL when track changes
  useEffect(() => {
    if (!oldTrackId || playbackState?.trackId !== oldTrackId) {
      if (playbackState?.imgUrl) {
        setCoverUrl(playbackState.imgUrl);
      }
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
        <div style={plainLyrics}>
          {playbackState.lyrics.plain}
        </div>
      );
    }

    return <div>Lyrics unavailable for this song</div>;
  }

  return (
    <div
    style={{
      ...container,
      //opacity: isHovered ? 0.4 : 0.85,
      transition: "opacity 0.15s ease"
    }}
    >
      <div style={{...lyricsContainer, backgroundImage: bg || undefined, backgroundColor: !bg ? accent : undefined}}>
        <img style={coverImage} src={coverUrl}></img>
        {renderLyrics()}
      </div>
      <div style={{...songBar}}>
        <div style={{...songTitleContainer, color: isColorDark(accent) ? lightenColor(accent): accent}}>{displaySong}</div>
        <div style={artistNameContainer}>{displayArtist}</div>
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
  boxSizing: 'border-box'
};

const plainLyrics: React.CSSProperties = {
  width: '100%',
  height: '100%',
  display: 'flex',
  flexWrap: 'wrap',
  whiteSpace: 'pre-wrap',
  lineHeight: 2,
  fontSize: '25px',
  color: colors.text.primary,
  textShadow: '0 2px 8px rgba(0,0,0,0.5)',
  overflowY: 'auto',
  fontWeight: 800,
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
