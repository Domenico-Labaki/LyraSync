// TokenStore.ts
import keytar from "keytar";

const SERVICE = "spotify-lyrics-overlay";

let accessToken: string | undefined;

// Access token stored in memory only

export function setAccessToken(token: string) {
    accessToken = token;
}

export function getAccessToken() {
    return accessToken;
}

// Refresh token securely stored for persistent login

export async function setRefreshToken(token: string) {
    await keytar.setPassword(SERVICE, "refresh_token", token);
}

export async function getRefreshToken(): Promise<string | null> {
    return await keytar.getPassword(SERVICE, "refresh_token");
}

export function clearToken() {
    accessToken = undefined;
}

export async function clearCachedToken() {
    await keytar.deletePassword(SERVICE, "refresh_token");
}

// Guest mode preference stored persistently

export async function setGuestModePreference(enabled: boolean) {
    if (enabled) {
        await keytar.setPassword(SERVICE, "guest_mode_enabled", "true");
    } else {
        await keytar.deletePassword(SERVICE, "guest_mode_enabled");
    }
}

export async function getGuestModePreference(): Promise<boolean> {
    const value = await keytar.getPassword(SERVICE, "guest_mode_enabled");
    return value === "true";
}

export async function clearGuestModePreference() {
    await keytar.deletePassword(SERVICE, "guest_mode_enabled");
}
