import axios from 'axios';

const clientId = process.env.SPOTIFY_CLIENT_ID!;
const clientSecret = process.env.SPOTIFY_CLIENT_SECRET!;

export async function refreshAccessToken(
    refreshToken: string
): Promise<string> {

    const params = new URLSearchParams();
    params.append('grant_type', 'refresh_token');
    params.append('refresh_token', refreshToken);

    const authString = Buffer
        .from(`${clientId}:${clientSecret}`)
        .toString('base64');

    const response = await axios.post(
        'https://accounts.spotify.com/api/token',
        params,
        {
            headers: {
                Authorization: `Basic ${authString}`,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        }
    );

    return response.data.access_token;
}
