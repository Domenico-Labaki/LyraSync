import ColorThief from "colorthief";

export async function getAccentColor(imageUrl: string) {
    if (imageUrl == '') { return hexToRGB(colors.primary.spotify) }
    return new Promise<string>((resolve) => {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.src = imageUrl;

        img.onload = () => {
        const colorThief = new ColorThief();
        const [r, g, b] = colorThief.getColor(img);
        resolve(`rgb(${r}, ${g}, ${b})`);
        };
    });
}

export function soften(rgb: any) {
  return rgb.replace("rgb", "rgba").replace(")", ", 0.8)");
}

function parseRGB(rgbString: string): [number, number, number] | null {
    const match = rgbString.match(/rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)/i);
    if (!match) return null;

    const r = parseInt(match[1], 10);
    const g = parseInt(match[2], 10);
    const b = parseInt(match[3], 10);

    return [r, g, b];
}

export function isColorDark(rgbString: string): boolean {
    const rgb = parseRGB(rgbString);
    if (!rgb) throw new Error("Invalid rgb string");

    const [r, g, b] = rgb;
    const brightness = (r * 299 + g * 587 + b * 114) / 1000;
    return brightness < 128;
}

export function lightenColor(rgbString: string, amount: number = 0.4): string {
    const rgb = parseRGB(rgbString);
    if (!rgb) throw new Error("Invalid rgb string");

    let [r, g, b] = rgb;
    r = Math.min(255, Math.round(r + (255 - r) * amount));
    g = Math.min(255, Math.round(g + (255 - g) * amount));
    b = Math.min(255, Math.round(b + (255 - b) * amount));

    return `rgb(${r}, ${g}, ${b})`;
}

export function hexToRGB(hex: string): string {
    // Remove the hash if present
    hex = hex.replace(/^#/, "");

    // Handle shorthand hex (#abc)
    if (hex.length === 3) {
        hex = hex.split("").map(c => c + c).join("");
    }

    if (hex.length !== 6) throw new Error("Invalid hex color");

    // Parse R, G, B values
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);

    return `rgb(${r}, ${g}, ${b})`;
}

export const colors = {
    primary: {
        spotify: '#1DB954',
    },
    text: {
        primary: '#B3B3B3',
        secondary: '#535353',
        accent: '#1DB954'
    },
    background: {
        primary: '#121212',
        secondary: '#212121'
    },
    status: {
        success: '#1DB954',
        error: '#E22134',
        warning: '#FFA500',
        info: '#3B82F6',
    }
};