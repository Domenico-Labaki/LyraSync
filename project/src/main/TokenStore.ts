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

export async function clearTokens() {
    accessToken = undefined;
    await keytar.deletePassword(SERVICE, "refresh_token");
}
