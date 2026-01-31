import { useEffect, useMemo, useRef, useState } from 'react';
import {
  parseSyncedLyrics,
  getActiveIndex
} from '../../utils/lyrics';
import '../index.css';

type Props = {
  lyricsRaw: string;
  progressMs: number;
};

export function SyncedLyrics({ lyricsRaw, progressMs }: Props) {
  const lyrics = useMemo(
    () => parseSyncedLyrics(lyricsRaw),
    [lyricsRaw]
  );

  const [activeIndex, setActiveIndex] = useState(0);
  const lineRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const index = Math.max(0, getActiveIndex(lyrics, progressMs));
    if (index !== activeIndex) {
      setActiveIndex(index);
    }
  }, [progressMs, lyrics, activeIndex]);

  useEffect(() => {
    if (activeIndex >= 0 && activeIndex < lyrics.length) {
      const el = lineRefs.current[activeIndex];
      if (el) {
        el.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
        });
      }
    }
  }, [activeIndex, lyrics.length]);

  return (
    <div className="lyrics-container">
      {lyrics.map((line, i) => (
        <div
          key={i}
          ref={el => {
            lineRefs.current[i] = el;
          }}
          className={`lyric-line ${
            i === activeIndex ? 'active' : ''
          }`}
        >
          {line.text}
        </div>
      ))}
    </div>
  );
}
