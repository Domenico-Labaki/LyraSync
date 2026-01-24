import React, { useEffect, useState } from 'react';
import { PlaybackState } from '../main/PlaybackState';
import { colors } from './theme/colors';

declare global {
  interface Window {
    api: {
      onPlaybackStateChanged: (callback: (state: PlaybackState) => void) => void;
      onHoverChanged: (callback: (hovered: boolean) => void) => void;
    };
  }
}

export default function App() {
  const [playbackState, setPlaybackState] = useState<PlaybackState | null>(null);

  useEffect(() => {
    window.api.onPlaybackStateChanged((state) => {
      setPlaybackState(state);
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

  return (
    <div
    style={{
      ...container,
      opacity: isHovered ? 0.15 : 0.85,
      transition: "opacity 0.15s ease"
    }}
    >
      <div style={lyricsContainer}>
        Lyrics go here
      </div>
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
  background: 'transparent',
  pointerEvents: 'auto',
  transition: 'opacity 0.1s ease',
  display: 'flex',
  flexDirection: 'column'
};

const lyricsContainer: React.CSSProperties = {
  width: '100%',
  height: '90%',
  paddingLeft: '20px',
  paddingRight: '20px',
  backgroundColor: colors.primary.spotify,
  borderTopLeftRadius: 8,
  borderTopRightRadius: 8
};

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
