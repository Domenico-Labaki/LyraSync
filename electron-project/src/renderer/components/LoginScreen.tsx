import React from 'react';
import brandLogo from '../../imgs/logo.png';
import { colors } from '../theme/colors';

interface LoginScreenProps {
  onSpotifyLogin: () => void;
  onGuestMode: () => void;
}

export function LoginScreen({ onSpotifyLogin, onGuestMode }: LoginScreenProps) {
  return (
    <div className="dragBar" style={styles.container}>
      <div style={styles.content}>
        <img src={brandLogo} width="100px" style={styles.logo} />
        
        <div style={styles.title}>Welcome to LyraSync</div>
        {/* <div style={styles.subtitle}>Choose how to sync lyrics with your music</div> */}

        <div style={styles.optionsContainer}>
          {/* Spotify Option */}
          <button
            onClick={onSpotifyLogin}
            style={styles.spotifyButton}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = 'scale(1.05)';
              e.currentTarget.style.boxShadow = '0 8px 16px rgba(29, 185, 84, 0.3)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'scale(1)';
              e.currentTarget.style.boxShadow = '0 4px 8px rgba(29, 185, 84, 0.2)';
            }}
          >
            {/* <div style={styles.buttonIcon}>🎵</div> */}
            <div style={styles.buttonTitle}>Sign in with Spotify</div>
            <div style={styles.buttonDescription}>
              Premium lyrics sync with Spotify playback
            </div>
          </button>

          {/* Divider */}
          <div style={styles.divider}>OR</div>

          {/* Guest Mode Option */}
          <button
            onClick={onGuestMode}
            style={styles.guestButton}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = 'scale(1.05)';
              e.currentTarget.style.boxShadow = '0 8px 16px rgba(76, 175, 80, 0.3)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'scale(1)';
              e.currentTarget.style.boxShadow = '0 4px 8px rgba(76, 175, 80, 0.2)';
            }}
          >
            {/* <div style={styles.buttonIcon}>🎧</div> */}
            <div style={styles.buttonTitle}>Guest Mode</div>
            <div style={styles.buttonDescription}>
              Use OS media controls (any music player)
            </div>
          </button>
        </div>
      </div>

      <div style={styles.footer}>
        © 2026 LyraSync
      </div>
    </div>
  );
}

const styles: { [key: string]: React.CSSProperties } = {
  container: {
    width: '100%',
    height: '100vh',
    backgroundColor: '#1B1C1F',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '5px',
    boxSizing: 'border-box',
    color: colors.text.primary,
  },
  content: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    gap: '0px',
  },
  logo: {
    marginBottom: '0px',
  },
  title: {
    fontSize: '24px',
    fontWeight: 'bold',
    color: colors.text.primary,
    marginTop: '0px',
  },
  subtitle: {
    fontSize: '14px',
    color: colors.text.secondary,
    marginBottom: '0px',
  },
  optionsContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0px',
    width: '100%',
    maxWidth: '300px',
  },
  spotifyButton: {
    padding: '20px',
    borderRadius: '8px',
    border: 'none',
    backgroundColor: '#1DB954',
    color: 'white',
    cursor: 'pointer',
    fontSize: '16px',
    fontWeight: '600',
    transition: 'all 0.3s ease',
    boxShadow: '0 4px 8px rgba(29, 185, 84, 0.2)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '2px',
  },
  guestButton: {
    padding: '20px',
    borderRadius: '8px',
    border: 'none',
    backgroundColor: '#4CAF50',
    color: 'white',
    cursor: 'pointer',
    fontSize: '16px',
    fontWeight: '600',
    transition: 'all 0.3s ease',
    boxShadow: '0 4px 8px rgba(76, 175, 80, 0.2)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '2px',
  },
  buttonIcon: {
    fontSize: '28px',
  },
  buttonTitle: {
    fontSize: '16px',
    fontWeight: 'bold',
  },
  buttonDescription: {
    fontSize: '12px',
    opacity: 0.9,
    marginTop: '0px',
  },
  divider: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: colors.text.secondary,
    fontSize: '12px',
    margin: '0px 0',
  },
  footer: {
    fontSize: '12px',
    color: colors.text.secondary,
  }
};
