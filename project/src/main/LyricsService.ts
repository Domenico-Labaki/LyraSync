import axios from "axios";

export type LyricsResult = {
  plain: string;
  synced?: string; // LRC format
  source: "lrclib" | "lyrics.ovh";
};

export class LyricsService {
  static async getLyrics(artist: string, title: string): Promise<LyricsResult | null> {

    // LRCLIB as main provider
    const lrclib = await this.fromLrclib(artist, title);
    if (lrclib) return lrclib;
    
    // Fallback to lyrics.ovh
    const ovh = await this.fromOvh(artist, title);
    if (ovh) return ovh;

    return null;
  }

  private static async fromLrclib(artist: string, title: string): Promise<LyricsResult | null> {
    try {
      const { data } = await axios.get(
        "https://lrclib.net/api/search",
        {
          params: {
            artist_name: artist,
            track_name: title
          }
        }
      );

      if (!data?.length) return null;

      const best = data[0];

      if (!best.plainLyrics && !best.syncedLyrics) return null;

      return {
        plain: best.plainLyrics ?? "",
        synced: best.syncedLyrics ?? undefined,
        source: "lrclib"
      };
    } catch {
      return null;
    }
  }

  private static async fromOvh(artist: string, title: string): Promise<LyricsResult | null> {
    try {
      const { data } = await axios.get(
        `https://api.lyrics.ovh/v1/${encodeURIComponent(artist)}/${encodeURIComponent(title)}`
      );

      if (!data?.lyrics) return null;

      return {
        plain: data.lyrics,
        source: "lyrics.ovh"
      };
    } catch {
      return null;
    }
  }
}
