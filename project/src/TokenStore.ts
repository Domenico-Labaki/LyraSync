// TokenStore.ts
let accessToken: string;
let refreshToken: string;

export function setAccessToken(token: string) {
    accessToken = token;
}

export function getAccessToken() {
    return accessToken;
}

export function setRefreshToken(token: string) {
    refreshToken = token;
}

export function getRefreshToken() {
    return refreshToken;
}
