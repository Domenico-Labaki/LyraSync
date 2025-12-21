import React, { useEffect, useState } from "react";
import { PlaybackState } from "../main/PlaybackState";

declare global {
  interface Window {
    api: {
      onPlaybackStateChanged: (callback: (state: PlaybackState) => void) => void;
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

  const displayText = playbackState
    ? `${playbackState.trackName} - ${playbackState.artist}`
    : "Lyra Sync Overlay";

  return (
    <div style={container}>
      <p style={lyrics}>{displayText}</p>
    </div>
  );
}

const container: React.CSSProperties = {
  width: "100vw",
  height: "100vh",
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
  background: "black",
  pointerEvents: "none"
};

const lyrics: React.CSSProperties = {
  color: "white",
  fontSize: "28px",
  fontWeight: 500
};
