import React, { useEffect, useState } from 'react';
import { colors } from './theme/colors';
import { PlaybackWithLyrics } from '../main/PlaybackState';

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

  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    window.api.onHoverChanged(setIsHovered);
  }, []);

  function renderLyrics() {
    if (!playbackState?.lyrics) {
      return <div>Lyrics unavailable for this song</div>;
    }

    if (playbackState.lyrics.synced) {
      return(
        <div>
          Synced lyrics are available
        </div>
      );
    }

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
      opacity: isHovered ? 0.15 : 0.85,
      transition: "opacity 0.15s ease"
    }}
    >
      {<div style={lyricsContainer}>
        {renderLyrics()}
      </div>}
      <div style={songBar}>
        <div style={songTitleContainer}>{displaySong}</div>
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
  width: '100%',
  height: '90%',
  backgroundColor: colors.primary.spotify,
  borderTopLeftRadius: 8,
  borderTopRightRadius: 8,
  overflow: 'clip',
  padding: 20,
  // Padding is taken into consideration for width calculation (child can have 100% width and not go over padding zone)
  boxSizing: 'border-box'
};

const plainLyrics: React.CSSProperties = {
  width: '100%',
  display: 'flex',
  flexWrap: 'wrap'
}

const songBar: React.CSSProperties = {
  width: '100%',
  height: '10%',
  backgroundColor: colors.background.secondary,
  display: 'flex',
  flexDirection: 'row',
  alignItems: 'center',
  borderBottomLeftRadius: 8,
  borderBottomRightRadius: 8
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
