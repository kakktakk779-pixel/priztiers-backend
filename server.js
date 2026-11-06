const express = require('express');
const fetch = require('node-fetch');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());

// Ваши данные приложения Discord Developer Portal
const CLIENT_ID = '1561648119584784444';
const CLIENT_SECRET = 'NacJo3BKMzebTYrhn6sHFkHUzpl4cCP4';

// Простая файловая баз данных для хранения привязок аккаунтов и дат создания
const DB_FILE = path.join(__dirname, 'database.json');

function readDb() {
    if (!fs.existsSync(DB_FILE)) {
        return { users: {}, bgs: {} };
    }
    try {
        return JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
    } catch (e) {
        return { users: {}, bgs: {} };
    }
}

function writeDb(data) {
    fs.writeFileSync(DB_FILE, JSON.stringify(data, null, 2), 'utf8');
}

// Эндпоинт для обмена одноразового code на настоящий Discord ID
app.post('/api/auth/discord', async (req, res) => {
    const { code, redirect_uri } = req.body;

    if (!code) {
        return res.status(400).json({ error: 'Код не предоставлен' });
    }

    try {
        // 1. Запрос к API Discord для получения access_token
        const tokenResponse = await fetch('https://discord.com/api/oauth2/token', {
            method: 'POST',
            body: new URLSearchParams({
                client_id: CLIENT_ID,
                client_secret: CLIENT_SECRET,
                grant_type: 'authorization_code',
                code: code,
                redirect_uri: redirect_uri || 'https://priztiers.pages.dev/',
            }),
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
        });

        const tokenData = await tokenResponse.json();

        if (!tokenData.access_token) {
            return res.status(400).json({ error: 'Не удалось получить токен авторизации Discord' });
        }

        // 2. Получение уникального профиля пользователя
        const userResponse = await fetch('https://discord.com/api/users/@me', {
            headers: {
                authorization: `${tokenData.token_type} ${tokenData.access_token}`,
            },
        });

        const userData = await userResponse.json();
        const discordId = userData.id;

        const db = readDb();
        
        // Если пользователь входит впервые — фиксируем дату создания аккаунта
        if (!db.users[discordId]) {
            const options = { day: 'numeric', month: 'long', year: 'numeric' };
            db.users[discordId] = {
                discord_id: discordId,
                username: null, // Установится при первой регистрации ника
                created_at: new Date().toLocaleDateString('ru-RU', options)
            };
            writeDb(db);
        }

        res.json({
            discord_id: discordId,
            username: db.users[discordId].username,
            created_at: db.users[discordId].created_at
        });

    } catch (error) {
        console.error('Ошибка OAuth2:', error);
        res.status(500).json({ error: 'Ошибка сервера при авторизации' });
    }
});

// Сохранение привязанного ника к Discord ID
app.post('/api/user/set-nick', (req, res) => {
    const { discord_id, nickname } = req.body;
    if (!discord_id || !nickname) return res.status(400).json({ error: 'Неверные данные' });

    const db = readDb();
    if (db.users[discord_id]) {
        db.users[discord_id].username = nickname;
        writeDb(db);
        return res.json({ success: true, username: nickname });
    }

    res.status(404).json({ error: 'Пользователь не найден' });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Сервер авторизации PrizTiers запущен на порту ${PORT}`);
});
