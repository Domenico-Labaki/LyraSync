export type LyricLine = {
  time: number; // ms
  text: string;
};

export function parseSyncedLyrics(raw: string): LyricLine[] {
  return raw
    .split('\n')
    .map(line => {
      const match = line.match(/\[(\d+):(\d+\.\d+)\]\s*(.*)/);
      if (!match) return null;

      const minutes = parseInt(match[1], 10);
      const seconds = parseFloat(match[2]);
      const time = minutes * 60 * 1000 + seconds * 1000;

      return { time, text: match[3] };
    })
    .filter(Boolean) as LyricLine[];
}

export function getActiveIndex(
  lyrics: LyricLine[],
  progressMs: number
) {
  for (let i = lyrics.length - 1; i >= 0; i--) {
    if (progressMs >= lyrics[i].time) return i;
  }
  return -1;
}