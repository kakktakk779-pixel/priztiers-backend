const express = require('express');
const fetch = require('node-fetch');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());

const CLIENT_ID = '1561648119584784444';
const CLIENT_SECRET = 'NacJo3BKMzebTYrhn6sHFkHUzpl4cCP4';

// Путь к файлу базы данных
const DB_FILE = path.join(__dirname, 'database.json');

function readDb() {
    if (!fs.existsSync(DB_FILE)) {
        return { users: {}, players: {}, views: {}, bgs: {}, skins: {} };
    }
    try {
        const data = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
        if (!data.players) data.players = {};
        if (!data.users) data.users = {};
        if (!data.views) data.views = {};
        if (!data.bgs) data.bgs = {};
        if (!data.skins) data.skins = {};
        return data;
    } catch (e) {
        return { users: {}, players: {}, views: {}, bgs: {}, skins: {} };
    }
}

function writeDb(data) {
    fs.writeFileSync(DB_FILE, JSON.stringify(data, null, 2), 'utf8');
}

// Авторизация через Discord OAuth2
app.post('/api/auth/discord', async (req, res) => {
    const { code, redirect_uri } = req.body;
    if (!code) return res.status(400).json({ error: 'Код не предоставлен' });

    try {
        const tokenResponse = await fetch('https://discord.com/api/oauth2/token', {
            method: 'POST',
            body: new URLSearchParams({
                client_id: CLIENT_ID,
                client_secret: CLIENT_SECRET,
                grant_type: 'authorization_code',
                code: code,
                redirect_uri: redirect_uri || 'https://priztiers.pages.dev/',
            }),
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        });

        const tokenData = await tokenResponse.json();
        if (!tokenData.access_token) {
            return res.status(400).json({ error: 'Не удалось получить токен Discord' });
        }

        const userResponse = await fetch('https://discord.com/api/users/@me', {
            headers: { authorization: `${tokenData.token_type} ${tokenData.access_token}` },
        });

        const userData = await userResponse.json();
        const discordId = userData.id;

        const db = readDb();
        
        if (!db.users[discordId]) {
            const options = { day: 'numeric', month: 'long', year: 'numeric' };
            db.users[discordId] = {
                discord_id: discordId,
                username: null,
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

// Сохранение и привязка ника
app.post('/api/user/set-nick', (req, res) => {
    const { discord_id, nickname } = req.body;
    if (!discord_id || !nickname) return res.status(400).json({ error: 'Неверные данные' });

    const db = readDb();
    db.users[discord_id].username = nickname;
    
    if (!db.players[nickname]) {
        db.players[nickname] = { beast: 0, mace: 0, carts: 0, pts: 0, title: '' };
    }
    writeDb(db);

    res.json({ success: true, username: nickname });
});

// Получение всей базы данных игроков и настроек для сайта
app.get('/api/data/get', (req, res) => {
    const db = readDb();
    res.json({
        players: db.players,
        views: db.views,
        bgs: db.bgs,
        skins: db.skins
    });
});

// Синхронизация данных игрока (тиры, фоны, скины, очки)
app.post('/api/data/save', (req, res) => {
    const { players, views, bgs, skins } = req.body;
    const db = readDb();
    
    if (players) db.players = players;
    if (views) db.views = views;
    if (bgs) db.bgs = bgs;
    if (skins) db.skins = skins;

    writeDb(db);
    res.json({ success: true });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Сервер авторизации PrizTiers запущен на порту ${PORT}`);
});
