import React from "react";

export default function App() {
  return (
    <div style={container}>
      <p style={lyrics}>Lyra Sync Overlay</p>
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
