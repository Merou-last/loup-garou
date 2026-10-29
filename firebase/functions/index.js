const { onRequest } = require('firebase-functions/v2/https');
const { defineSecret, defineString } = require('firebase-functions/params');
const admin = require('firebase-admin');
const crypto = require('crypto');

admin.initializeApp();
const DISCORD_CLIENT_SECRET = defineSecret('DISCORD_CLIENT_SECRET');
const DISCORD_BOT_TOKEN = defineSecret('DISCORD_BOT_TOKEN');
const DISCORD_CLIENT_ID = defineString('DISCORD_CLIENT_ID');
const DISCORD_GUILD_ID = defineString('DISCORD_GUILD_ID', { default: '1564749301203079422' });
const SITE_ORIGIN = defineString('SITE_ORIGIN');
const COOKIE_NAME = 'ya_discord_oauth_state';

function cookieValue(header, name) {
  const part = (header || '').split(';').map(x => x.trim()).find(x => x.startsWith(name + '='));
  return part ? decodeURIComponent(part.slice(name.length + 1)) : '';
}
function sendError(res, status, message) {
  res.status(status).type('text/plain').send(message);
}

// Open this URL in a popup: https://REGION-PROJECT.cloudfunctions.net/discordStart
exports.discordStart = onRequest({ cors: false }, async (req, res) => {
  if (req.method !== 'GET') return sendError(res, 405, 'Method not allowed');
  const state = crypto.randomBytes(24).toString('hex');
  res.set('Set-Cookie', `${COOKIE_NAME}=${encodeURIComponent(state)}; Max-Age=600; Path=/; Secure; HttpOnly; SameSite=Lax`);
  const redirectUri = `https://${process.env.FUNCTION_REGION || 'us-central1'}-${process.env.GCLOUD_PROJECT}.cloudfunctions.net/discordCallback`;
  const params = new URLSearchParams({
    client_id: DISCORD_CLIENT_ID.value(),
    response_type: 'code',
    redirect_uri: redirectUri,
    scope: 'identify',
    state,
    prompt: 'none'
  });
  res.redirect(302, `https://discord.com/oauth2/authorize?${params.toString()}`);
});

exports.discordCallback = onRequest({ secrets: [DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN], cors: false }, async (req, res) => {
  if (req.method !== 'GET') return sendError(res, 405, 'Method not allowed');
  const expectedState = cookieValue(req.headers.cookie, COOKIE_NAME);
  const receivedState = String(req.query.state || '');
  if (!expectedState || !receivedState || expectedState !== receivedState) return sendError(res, 400, 'OAuth state mismatch. Close this window and try again.');
  if (req.query.error) return sendError(res, 403, 'Discord login was cancelled or denied.');
  const code = String(req.query.code || '');
  if (!code) return sendError(res, 400, 'Missing OAuth code.');

  const redirectUri = `https://${process.env.FUNCTION_REGION || 'us-central1'}-${process.env.GCLOUD_PROJECT}.cloudfunctions.net/discordCallback`;
  try {
    const tokenResponse = await fetch('https://discord.com/api/v10/oauth2/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: DISCORD_CLIENT_ID.value(),
        client_secret: DISCORD_CLIENT_SECRET.value(),
        grant_type: 'authorization_code', code, redirect_uri: redirectUri
      })
    });
    if (!tokenResponse.ok) throw new Error('Discord token exchange failed');
    const oauth = await tokenResponse.json();
    const userResponse = await fetch('https://discord.com/api/v10/users/@me', {
      headers: { Authorization: `Bearer ${oauth.access_token}` }
    });
    if (!userResponse.ok) throw new Error('Could not read Discord profile');
    const user = await userResponse.json();

    // Membership is checked server-side with the bot token; browser claims are never trusted.
    const memberResponse = await fetch(`https://discord.com/api/v10/guilds/${DISCORD_GUILD_ID.value()}/members/${user.id}`, {
      headers: { Authorization: `Bot ${DISCORD_BOT_TOKEN.value()}` }
    });
    if (memberResponse.status === 404) return sendError(res, 403, 'You must join the Youcef Alpacino Discord server before logging in.');
    if (!memberResponse.ok) throw new Error(`Discord member check failed (${memberResponse.status})`);

    const uid = `discord_${user.id}`;
    const customToken = await admin.auth().createCustomToken(uid, {
      discordMember: true,
      guildId: DISCORD_GUILD_ID.value(),
      discordId: user.id,
      discordUsername: user.username
    });
    const avatarUrl = user.avatar
      ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=128`
      : `https://cdn.discordapp.com/embed/avatars/${Number(user.discriminator || 0) % 5}.png`;
    const origin = JSON.stringify(SITE_ORIGIN.value());
    const token = JSON.stringify(customToken);
    const profile = JSON.stringify({ id: user.id, username: user.username, globalName: user.global_name || user.username, avatarUrl });
    res.set('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'");
    res.set('Cache-Control', 'no-store');
    res.status(200).type('html').send(`<!doctype html><html lang="en"><meta charset="utf-8"><title>Discord login</title><body><p>Discord membership verified. You can close this window.</p><script>
      (function(){var target=${origin}; if(window.opener){window.opener.postMessage({type:'youcef-discord-auth',token:${token},profile:${profile}},target);} window.close();})();
    </script></body></html>`);
  } catch (err) {
    console.error('Discord OAuth verification failed:', err.message);
    sendError(res, 500, 'Could not verify Discord login. Check the Firebase Function logs and configuration.');
  }
});
