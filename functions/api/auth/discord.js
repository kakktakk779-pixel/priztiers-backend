export async function onRequestPost(context) {
    try {
        const { request, env } = context;
        const body = await request.json();
        const { code, redirect_uri } = body;

        if (!code) {
            return new Response(JSON.stringify({ error: 'Не передан код авторизации (code)' }), {
                status: 400,
                headers: { 'Content-Type': 'application/json' }
            });
        }

        const clientId = env.DISCORD_CLIENT_ID;
        const clientSecret = env.DISCORD_CLIENT_SECRET;

        if (!clientId || !clientSecret) {
            return new Response(JSON.stringify({
                error: 'Не настроены переменные окружения DISCORD_CLIENT_ID или DISCORD_CLIENT_SECRET в Cloudflare',
                debug: {
                    hasClientId: Boolean(clientId),
                    hasClientSecret: Boolean(clientSecret),
                    envKeys: Object.keys(env || {})
                }
            }), {
                status: 500,
                headers: { 'Content-Type': 'application/json' }
            });
        }

        // Обмениваем code на access_token у Discord
        const tokenResponse = await fetch('https://discord.com/api/oauth2/token', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
                client_id: clientId,
                client_secret: clientSecret,
                grant_type: 'authorization_code',
                code: code,
                redirect_uri: redirect_uri,
            }),
        });

        const tokenData = await tokenResponse.json();

        if (!tokenResponse.ok || !tokenData.access_token) {
            return new Response(JSON.stringify({ error: 'Не удалось получить токен от Discord', details: tokenData }), {
                status: 400,
                headers: { 'Content-Type': 'application/json' }
            });
        }

        // Запрашиваем информацию о пользователе
        const userResponse = await fetch('https://discord.com/api/users/@me', {
            headers: {
                Authorization: `Bearer ${tokenData.access_token}`,
            },
        });

        const userData = await userResponse.json();

        if (!userResponse.ok || !userData.id) {
            return new Response(JSON.stringify({ error: 'Не удалось получить профиль пользователя Discord', details: userData }), {
                status: 400,
                headers: { 'Content-Type': 'application/json' }
            });
        }

        // Возвращаем на сайт ID пользователя и дату регистрации (если Discord ее отдает, либо текущую)
        return new Response(JSON.stringify({
            discord_id: userData.id,
            username: userData.username,
            created_at: new Date().toLocaleDateString('ru-RU')
        }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
        });

    } catch (err) {
        return new Response(JSON.stringify({ error: 'Внутренняя ошибка сервера Cloudflare', message: err.message }), {
            status: 500,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}
```[cite: 18]
