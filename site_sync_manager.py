import sqlite3
import json
import os
from datetime import datetime

DB_NAME = "priztiers.db"
LIVE_JSON_BACKUP = "site_state_live.json"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_sync_database():
    """Инициализация единой базы данных для сайта и Discord-бота"""
    with get_db() as conn:
        # --- ДАННЫЕ САЙТА И ПРОФИЛЕЙ ---
        # 1. Игроки, никнеймы, скины, позы, фоны
        conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                discord_id TEXT PRIMARY KEY,
                ign TEXT NOT NULL,
                skin_url TEXT DEFAULT '',
                pose_url TEXT DEFAULT '',
                background_url TEXT DEFAULT '',
                updated_at TEXT
            )
        """)
        
        # 2. Тиры игроков по китам
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_tiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT,
                kit_name TEXT,
                tier TEXT,
                updated_at TEXT,
                FOREIGN KEY(discord_id) REFERENCES players(discord_id)
            )
        """)

        # 3. Снапшоты и кэш для сайта
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_snapshots (
                key TEXT PRIMARY KEY,
                data TEXT,
                updated_at TEXT
            )
        """)

        # --- ДАННЫЕ ДИСКОРД-БОТА ---
        # 4. Живые очереди на тесты
        conn.execute("""
            CREATE TABLE IF NOT EXISTS live_queues_db (
                discord_id TEXT PRIMARY KEY,
                ign TEXT,
                kit_name TEXT,
                status TEXT,
                joined_at TEXT
            )
        """)

        # 5. Статистика тестеров
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tester_stats (
                tester_id TEXT PRIMARY KEY,
                tests_passed INTEGER DEFAULT 0,
                tests_failed INTEGER DEFAULT 0
            )
        """)

        # 6. Динамические настройки серверов и ролей
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dynamic_roles (
                guild_id TEXT PRIMARY KEY,
                staff_role_id TEXT,
                result_channel_id TEXT
            )
        """)

        conn.commit()
    
    export_state_to_json()

def export_state_to_json():
    """Экспорт актуальных данных для сайта в реальном времени"""
    with get_db() as conn:
        players_data = [dict(row) for row in conn.execute("SELECT * FROM players").fetchall()]
        tiers_data = [dict(row) for row in conn.execute("SELECT * FROM user_tiers").fetchall()]

        full_state = {
            "last_updated": datetime.utcnow().isoformat(),
            "players": players_data,
            "tiers": tiers_data,
            "leaderboard_summary": generate_leaderboard_summary(players_data, tiers_data)
        }

        temp_file = LIVE_JSON_BACKUP + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(full_state, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, LIVE_JSON_BACKUP)

def generate_leaderboard_summary(players, tiers):
    leaderboard = {}
    for p in players:
        d_id = p["discord_id"]
        leaderboard[d_id] = {
            "ign": p["ign"],
            "skin_url": p["skin_url"],
            "pose_url": p["pose_url"],
            "background_url": p["background_url"],
            "kits": {}
        }
    for t in tiers:
        d_id = t["discord_id"]
        if d_id in leaderboard:
            leaderboard[d_id]["kits"][t["kit_name"]] = t["tier"]
    return list(leaderboard.values())