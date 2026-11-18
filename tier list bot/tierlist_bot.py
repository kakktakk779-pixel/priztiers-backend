import disnake
from disnake.ext import commands
import sqlite3
import os
import sys
import io
import asyncio
import re
import aiohttp
import json
import logging
import random
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("PrizTiersBot")

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DB_FILE = "priztiers.db"
ETERNAL_DB_FILE = "priztiers_alltime.db"
BACKUP_DIR = "backups_save"
BG_DIR = "backgrounds"
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(BG_DIR, exist_ok=True)

def get_db_connection(db_path=DB_FILE):
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

def init_db():
    with get_db_connection(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                discord_id TEXT PRIMARY KEY,
                username TEXT,
                ign TEXT,
                server_name TEXT,
                ping TEXT,
                discord_tag TEXT,
                created_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_tiers (
                discord_id TEXT,
                kit TEXT,
                tier TEXT,
                last_tested TEXT,
                PRIMARY KEY (discord_id, kit)
            )
        """)
        try:
            cursor.execute("ALTER TABLE user_tiers ADD COLUMN last_tested TEXT")
        except sqlite3.OperationalError:
            pass

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS match_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT,
                ign TEXT,
                kit TEXT,
                old_tier TEXT,
                new_tier TEXT,
                score TEXT,
                tester_id TEXT,
                tester_ign TEXT,
                timestamp TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_backgrounds (
                discord_id TEXT PRIMARY KEY,
                file_path TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_season_wins (
                discord_id TEXT,
                season_number INTEGER,
                PRIMARY KEY (discord_id, season_number)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cursor.execute("SELECT value FROM bot_meta WHERE key = 'current_season'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO bot_meta (key, value) VALUES ('current_season', '1')")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS server_kits (
                guild_id TEXT PRIMARY KEY,
                kit TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tester_stats (
                discord_id TEXT,
                kit TEXT,
                test_count INTEGER,
                PRIMARY KEY (discord_id, kit)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_leaderboards (
                guild_id TEXT,
                channel_id TEXT,
                message_id TEXT,
                lb_type TEXT,
                PRIMARY KEY (guild_id, lb_type)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_queues_db (
                kit TEXT PRIMARY KEY,
                is_open INTEGER,
                active_testers TEXT,
                queue_data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dynamic_roles (
                kit TEXT,
                role_key TEXT,
                role_id INTEGER,
                PRIMARY KEY (kit, role_key)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS result_channels (
                kit TEXT PRIMARY KEY,
                channel_id TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue_channels (
                kit TEXT PRIMARY KEY,
                channel_id TEXT,
                message_id TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_renames (
                discord_id TEXT PRIMARY KEY,
                last_changed TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tester_kit_alerts (
                kit TEXT,
                discord_id TEXT,
                enabled INTEGER DEFAULT 0,
                PRIMARY KEY (kit, discord_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS discord_channels_state (
                channel_id TEXT PRIMARY KEY,
                guild_id TEXT,
                category_id TEXT,
                category_name TEXT,
                name TEXT,
                channel_type TEXT,
                topic TEXT,
                position INTEGER,
                slowmode_delay INTEGER,
                nsfw INTEGER,
                overwrites_json TEXT,
                updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_backups (
                slot_id INTEGER PRIMARY KEY,
                backup_name TEXT,
                file_path TEXT,
                timestamp TEXT
            )
        """)
        conn.commit()
        cursor.execute("UPDATE live_queues_db SET active_testers = '[]', is_open = 0, queue_data = '[]'")
        conn.commit()

    with get_db_connection(ETERNAL_DB_FILE) as econn:
        ecursor = econn.cursor()
        ecursor.execute("""
            CREATE TABLE IF NOT EXISTS eternal_messages (
                message_id TEXT PRIMARY KEY,
                guild_id TEXT,
                guild_name TEXT,
                channel_id TEXT,
                channel_name TEXT,
                category_name TEXT,
                author_id TEXT,
                author_name TEXT,
                is_bot INTEGER,
                content TEXT,
                embeds_json TEXT,
                attachments_json TEXT,
                created_at TEXT
            )
        """)
        ecursor.execute("""
            CREATE TABLE IF NOT EXISTS eternal_channels_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                guild_name TEXT,
                channel_id TEXT,
                category_name TEXT,
                name TEXT,
                channel_type TEXT,
                topic TEXT,
                position INTEGER,
                overwrites_json TEXT,
                snapshot_time TEXT
            )
        """)
        ecursor.execute("""
            CREATE TABLE IF NOT EXISTS eternal_snapshots_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_by TEXT,
                guild_id TEXT,
                guild_name TEXT,
                channels_count INTEGER,
                messages_count INTEGER,
                created_at TEXT
            )
        """)
        econn.commit()

init_db()

KITS = ["Beast", "Mace", "Carts"]

TIER_POINTS = {
    "HT1": 60, "RHT1": 55, "LT1": 45, "RLT1": 40, "HT2": 30, "RHT2": 25,
    "LT2": 20, "RLT2": 15, "HT3": 10, "LT3": 6, "HT4": 5, "LT4": 4, "HT5": 3, "LT5": 2
}

DEFAULT_ROLES = {
    "Beast": {
        "tester": 1561642160112144401, "senior_tester": 1561642160112144402, "head_tester": 1561642160112144403,
        "helper": 1561642160112144404, "moderator": 1561642160120659971, "senior_moderator": 1561642160120659972,
        "tier_manager": 1561642160120659973, "senior_tier_manager": 1561642160120659974, "curator": 1561642160120659977,
        "project_head": 1561642160120659978, "network_manager": 1561642160124596329, "tier_admin": 1561642160124596327,
        "network_owner": 1561642160133111839, "admin": 1561642160124596332,
        "whitelist": 1561642159751430289, "member": 1561642159751430290, "restricted": 1561642159751430291,
        "news": 1569716476783366174, "polls": 1569717142134325278, "ping": 1569717200175108196,
        "matchmaking": 1569727930496716923,
        "tier_roles": {
            "LT5": 1561642159751430292, "HT5": 1561642159751430293, "LT4": 1561642160103759972, "HT4": 1561642160103759973,
            "LT3": 1561642160103759974, "HT3": 1561642160103759975, "RLT2": 1561642160103759976, "LT2": 1561642160103759977,
            "RHT2": 1561642160103759978, "HT2": 1561642160103759979, "RLT1": 1561642160103759980, "LT1": 1561642160112144381,
            "RHT1": 1561642160112144396, "HT1": 1561642160112144397
        }
    },
    "Mace": {
        "tester": 1561642412835737615, "senior_tester": 1561642412835737616, "head_tester": 1561642412835737617,
        "helper": 1561642412835737618, "moderator": 1561642412843991084, "senior_moderator": 1561642412843991085,
        "tier_manager": 1561642412843991086, "senior_tier_manager": 1561642412843991087, "curator": 1561642412843991090,
        "project_head": 1561642412843991091, "network_manager": 1561642412877684881, "tier_admin": 1561642412877684879,
        "network_owner": 1561642412890136616, "admin": 1561642412877684884,
        "whitelist": 1561642412391272513, "member": 1561642412391272514, "restricted": 1561642412391272515,
        "news": 1569714459012759674, "polls": 1569716576138170529, "ping": 1569714403232841852,
        "matchmaking": 1569640890795036723,
        "tier_roles": {
            "LT5": 1561642412391272516, "HT5": 1561642412391272517, "LT4": 1561642412823281694, "HT4": 1561642412823281695,
            "LT3": 1561642412823281696, "HT3": 1561642412823281697, "RLT2": 1561642412823281698, "LT2": 1561642412823281699,
            "RHT2": 1561642412823281700, "HT2": 1561642412823281701, "RLT1": 1561642412823281702, "LT1": 1561642412823281703,
            "RHT1": 1561642412835737610, "HT1": 1561642412835737611
        }
    },
    "Carts": {
        "tester": 1561643076034756651, "senior_tester": 1561643076034756652, "head_tester": 1561643076034756653,
        "helper": 1561643076034756654, "moderator": 1561643076139880448, "senior_moderator": 1561643076139880449,
        "tier_manager": 1561643076139880450, "senior_tier_manager": 1561643076139880451, "curator": 1561643076139880454,
        "project_head": 1561643076139880455, "network_manager": 1561643076232020041, "tier_admin": 1561643076232020039,
        "network_owner": 1561643076232020046, "admin": 1561643076232020044,
        "whitelist": 1561643075980365840, "member": 1561643075980365841, "restricted": 1561643075980365842,
        "news": 1569717464558870710, "polls": 1569717506074214410, "ping": 1569717533467217962,
        "matchmaking": 1569728013883678841,
        "tier_roles": {
            "LT5": 1561643076001341502, "HT5": 1561643076001341503, "LT4": 1561643076001341504, "HT4": 1561643075980365843,
            "LT3": 1561643076001341504, "HT3": 1561643076001341505, "RLT2": 1561643076001341506, "LT2": 1561643076001341507,
            "RHT2": 1561643076001341508, "HT2": 1561643076001341509, "RLT1": 1561643076001341510, "LT1": 1561643076001341511,
            "RHT1": 1561643076001341512, "HT1": 1561643076001341513
        }
    }
}

def get_role_id(kit: str, role_key: str) -> int:
    if not kit:
        kit = "Beast"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role_id FROM dynamic_roles WHERE kit = ? AND role_key = ?", (kit, role_key))
        row = cursor.fetchone()
        if row and row[0]:
            return int(row[0])
    fallback_kit = DEFAULT_ROLES.get(kit, DEFAULT_ROLES["Beast"])
    if role_key in fallback_kit:
        return fallback_kit[role_key]
    return fallback_kit.get("tier_roles", {}).get(role_key, 0)

def get_all_tier_role_ids(kit: str) -> dict:
    tiers = list(TIER_POINTS.keys())
    return {t: get_role_id(kit, t) for t in tiers if get_role_id(kit, t) != 0}

def set_role_id_db(kit: str, role_key: str, role_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO dynamic_roles (kit, role_key, role_id) VALUES (?, ?, ?)
            ON CONFLICT(kit, role_key) DO UPDATE SET role_id = ?
        """, (kit, role_key, role_id, role_id))
        conn.commit()

def get_result_channel_id(kit: str) -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT channel_id FROM result_channels WHERE kit = ?", (kit,))
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] else 0

def set_result_channel_db(kit: str, channel_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO result_channels (kit, channel_id) VALUES (?, ?)
            ON CONFLICT(kit) DO UPDATE SET channel_id = ?
        """, (kit, str(channel_id), str(channel_id)))
        conn.commit()

def save_queue_channel_db(kit: str, channel_id: int, message_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO queue_channels (kit, channel_id, message_id) VALUES (?, ?, ?)
            ON CONFLICT(kit) DO UPDATE SET channel_id = ?, message_id = ?
        """, (kit, str(channel_id), str(message_id), str(channel_id), str(message_id)))
        conn.commit()

def get_queue_channel_db(kit: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT channel_id, message_id FROM queue_channels WHERE kit = ?", (kit,))
        row = cursor.fetchone()
        if row and row[0] and row[1]:
            return int(row[0]), int(row[1])
        return None, None

def get_last_rename(discord_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT last_changed FROM player_renames WHERE discord_id = ?", (str(discord_id),))
        row = cursor.fetchone()
        if row and row[0]:
            try:
                return datetime.fromisoformat(row[0])
            except Exception:
                return None
        return None

def set_last_rename(discord_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO player_renames (discord_id, last_changed) VALUES (?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET last_changed = ?
        """, (str(discord_id), str(datetime.now(timezone.utc)), str(datetime.now(timezone.utc))))
        conn.commit()

def is_player_registered(discord_id) -> bool:
    d_id = str(discord_id)
    ign, _, _ = db_get_player_info(d_id)
    return bool(ign and ign.strip() and ign != "Unknown")

def check_test_cooldown(discord_id, kit: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT last_tested FROM user_tiers WHERE discord_id = ? AND kit = ?", (str(discord_id), kit))
        row = cursor.fetchone()
    if not row or not row[0]:
        return False, ""
    try:
        last_dt = datetime.fromisoformat(row[0])
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - last_dt
        cd = timedelta(days=14)
        if elapsed < cd:
            rem = cd - elapsed
            return True, f"{rem.days} дн. {rem.seconds // 3600} ч. {(rem.seconds % 3600) // 60} мин."
    except Exception:
        pass
    return False, ""

async def update_all_guilds_nickname(user_id: int, ign: str):
    for guild in bot.guilds:
        try:
            member = guild.get_member(user_id)
            if not member:
                member = await guild.fetch_member(user_id)
            if member and member.id != guild.owner_id:
                await member.edit(nick=ign)
        except Exception as e:
            logger.debug(f"Failed to update nickname in guild {guild.id}: {e}")

def serialize_channel_overwrites(channel: disnake.abc.GuildChannel) -> str:
    overwrites_list = []
    for target, overwrite in channel.overwrites.items():
        allow_val, deny_val = overwrite.pair()
        overwrites_list.append({
            "target_id": str(target.id),
            "target_type": "role" if isinstance(target, disnake.Role) else "member",
            "allow": allow_val.value,
            "deny": deny_val.value
        })
    return json.dumps(overwrites_list)

def save_channel_metadata_to_db(channel: disnake.abc.GuildChannel):
    if not hasattr(channel, "guild") or not channel.guild:
        return
    c_type = str(channel.type)
    cat_id = str(channel.category.id) if getattr(channel, "category", None) else ""
    cat_name = channel.category.name if getattr(channel, "category", None) else ""
    topic = getattr(channel, "topic", "") or ""
    pos = getattr(channel, "position", 0)
    slowmode = getattr(channel, "slowmode_delay", 0)
    nsfw = 1 if getattr(channel, "nsfw", False) else 0
    ow_json = serialize_channel_overwrites(channel)
    now_str = str(datetime.now(timezone.utc))

    with get_db_connection(DB_FILE) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO discord_channels_state
            (channel_id, guild_id, category_id, category_name, name, channel_type, topic, position, slowmode_delay, nsfw, overwrites_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(channel.id), str(channel.guild.id), cat_id, cat_name, channel.name, c_type, topic, pos, slowmode, nsfw, ow_json, now_str))
        conn.commit()

def sync_all_guilds_channels_state():
    for guild in bot.guilds:
        for channel in guild.channels:
            try:
                save_channel_metadata_to_db(channel)
            except Exception as e:
                logger.debug(f"Channel sync error {channel.id}: {e}")

bot = commands.Bot(command_prefix="!", intents=disnake.Intents.all())

queue_messages = {}

def calculate_total_points(discord_id):
    tiers = db_get_player_tiers(discord_id)
    return sum(TIER_POINTS.get(t, 0) for t in tiers.values())

def get_queue_state(kit: str) -> dict:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_open, active_testers, queue_data FROM live_queues_db WHERE kit = ?", (kit,))
        row = cursor.fetchone()
        if row:
            return {
                "is_open": bool(row[0]),
                "active_testers": json.loads(row[1]),
                "queue": json.loads(row[2]),
                "was_open": bool(row[0])
            }
        return {"is_open": False, "active_testers": [], "queue": [], "was_open": False}

def save_queue_state(kit: str, state: dict):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO live_queues_db (kit, is_open, active_testers, queue_data) VALUES (?, ?, ?, ?)
            ON CONFLICT(kit) DO UPDATE SET is_open = ?, active_testers = ?, queue_data = ?
        """, (
            kit, 1 if state["is_open"] else 0, json.dumps(state["active_testers"]), json.dumps(state["queue"]),
            1 if state["is_open"] else 0, json.dumps(state["active_testers"]), json.dumps(state["queue"])
        ))
        conn.commit()

def db_get_player_tiers(discord_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT kit, tier FROM user_tiers WHERE discord_id = ?", (str(discord_id),))
        rows = cursor.fetchall()
        return {row[0]: row[1] for row in rows}

def db_save_tier(discord_id, kit, tier, update_cooldown: bool = True):
    now_str = str(datetime.now(timezone.utc)) if update_cooldown else None
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if update_cooldown:
            cursor.execute("""
                INSERT INTO user_tiers (discord_id, kit, tier, last_tested) VALUES (?, ?, ?, ?)
                ON CONFLICT(discord_id, kit) DO UPDATE SET tier = ?, last_tested = ?
            """, (str(discord_id), kit, tier, now_str, tier, now_str))
        else:
            cursor.execute("""
                INSERT INTO user_tiers (discord_id, kit, tier) VALUES (?, ?, ?)
                ON CONFLICT(discord_id, kit) DO UPDATE SET tier = ?
            """, (str(discord_id), kit, tier, tier))
        conn.commit()

def db_get_player_info(discord_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ign, server_name, ping FROM players WHERE discord_id = ?", (str(discord_id),))
        row = cursor.fetchone()
        if row:
            return row[0] or "Unknown", row[1] or "Не указан", row[2] or "Не указан"
        return "Unknown", "Не указан", "Не указан"

def db_save_player_info(discord_id, ign, server_name, ping, username=None, discord_tag=None):
    d_id = str(discord_id)
    now_str = str(datetime.now(timezone.utc))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username, discord_tag, created_at FROM players WHERE discord_id = ?", (d_id,))
        existing = cursor.fetchone()
        final_username = username or (existing[0] if existing and existing[0] else None)
        final_tag = discord_tag or (existing[1] if existing and existing[1] else None)
        final_created = existing[2] if existing and existing[2] else now_str

        cursor.execute("""
            INSERT INTO players (discord_id, username, ign, server_name, ping, discord_tag, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                username = COALESCE(?, username),
                ign = ?,
                server_name = ?,
                ping = ?,
                discord_tag = COALESCE(?, discord_tag)
        """, (
            d_id, final_username, ign, server_name, ping, final_tag, final_created,
            final_username, ign, server_name, ping, final_tag
        ))
        conn.commit()

def db_log_match(discord_id, ign, kit, old_tier, new_tier, score, tester_id, tester_ign):
    now_str = str(datetime.now(timezone.utc))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO match_history (discord_id, ign, kit, old_tier, new_tier, score, tester_id, tester_ign, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(discord_id), ign, kit, old_tier or "None", new_tier, score, str(tester_id), tester_ign, now_str))
        conn.commit()

def db_get_player_background(discord_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM player_backgrounds WHERE discord_id = ?", (str(discord_id),))
        row = cursor.fetchone()
        return row[0] if row and row[0] else None

def db_set_player_background(discord_id, path):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO player_backgrounds (discord_id, file_path) VALUES (?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET file_path = ?
        """, (str(discord_id), path, path))
        conn.commit()

def db_get_season_wins(discord_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT season_number FROM player_season_wins WHERE discord_id = ? ORDER BY season_number ASC", (str(discord_id),))
        return [row[0] for row in cursor.fetchall()]

def db_get_current_season():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM bot_meta WHERE key = 'current_season'")
        row = cursor.fetchone()
        return int(row[0]) if row else 1

def db_set_current_season(val: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO bot_meta (key, value) VALUES ('current_season', ?)", (str(val),))
        conn.commit()

def db_get_server_kit(guild_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT kit FROM server_kits WHERE guild_id = ?", (str(guild_id),))
        row = cursor.fetchone()
        return row[0] if row else None

def db_set_server_kit(guild_id, kit):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO server_kits (guild_id, kit) VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET kit = ?
        """, (str(guild_id), kit, kit))
        conn.commit()

def db_increment_tester_test(discord_id, kit):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tester_stats (discord_id, kit, test_count) VALUES (?, ?, 1)
            ON CONFLICT(discord_id, kit) DO UPDATE SET test_count = test_count + 1
        """, (str(discord_id), kit))
        conn.commit()

def get_kit_theme(kit_name: str):
    k = (kit_name or "").lower()
    if "mace" in k:
        return {"main": (168, 85, 247), "glow": (147, 51, 234), "hex": 0xa855f7}
    elif "cart" in k or "карт" in k:
        return {"main": (239, 68, 68), "glow": (220, 38, 38), "hex": 0xef4444}
    else:
        return {"main": (96, 165, 250), "glow": (59, 130, 246), "hex": 0x3b82f6}

def parse_duration(duration_str: str) -> int:
    match = re.match(r"^(\d+)([smhd])$", duration_str.lower())
    if not match:
        return 3600
    val, unit = int(match.group(1)), match.group(2)
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return val * mult.get(unit, 3600)

def is_network_owner(member: disnake.Member, kit_name: str) -> bool:
    if member.id == member.guild.owner_id:
        return True
    owner_role_id = get_role_id(kit_name, "network_owner")
    role_ids = [r.id for r in member.roles]
    return owner_role_id != 0 and owner_role_id in role_ids

def is_tester_or_admin(member: disnake.Member, kit_name: str) -> bool:
    if is_network_owner(member, kit_name) or member.guild_permissions.administrator:
        return True
    role_ids = [r.id for r in member.roles]
    allowed = [
        get_role_id(kit_name, "tester"), get_role_id(kit_name, "senior_tester"),
        get_role_id(kit_name, "head_tester"), get_role_id(kit_name, "helper"),
        get_role_id(kit_name, "moderator"), get_role_id(kit_name, "senior_moderator"),
        get_role_id(kit_name, "tier_manager"), get_role_id(kit_name, "senior_tier_manager"),
        get_role_id(kit_name, "curator"), get_role_id(kit_name, "project_head"),
        get_role_id(kit_name, "network_manager"), get_role_id(kit_name, "tier_admin"),
        get_role_id(kit_name, "admin")
    ]
    return any(r in role_ids for r in allowed if r != 0)

def is_senior_or_head_tester(member: disnake.Member, kit_name: str) -> bool:
    if is_network_owner(member, kit_name) or member.guild_permissions.administrator:
        return True
    role_ids = [r.id for r in member.roles]
    allowed = [
        get_role_id(kit_name, "senior_tester"), get_role_id(kit_name, "head_tester"),
        get_role_id(kit_name, "tier_manager"), get_role_id(kit_name, "senior_tier_manager"),
        get_role_id(kit_name, "network_manager"), get_role_id(kit_name, "tier_admin"),
        get_role_id(kit_name, "admin")
    ]
    return any(r in role_ids for r in allowed if r != 0)

def is_head_tester_only(member: disnake.Member, kit_name: str) -> bool:
    if is_network_owner(member, kit_name) or member.guild_permissions.administrator:
        return True
    role_ids = [r.id for r in member.roles]
    allowed = [
        get_role_id(kit_name, "head_tester"), get_role_id(kit_name, "tier_manager"),
        get_role_id(kit_name, "senior_tier_manager"), get_role_id(kit_name, "network_manager"),
        get_role_id(kit_name, "tier_admin"), get_role_id(kit_name, "admin")
    ]
    return any(r in role_ids for r in allowed if r != 0)

def is_admin_or_higher(member: disnake.Member, kit_name: str) -> bool:
    if is_network_owner(member, kit_name) or member.guild_permissions.administrator:
        return True
    role_ids = [r.id for r in member.roles]
    allowed = [
        get_role_id(kit_name, "moderator"), get_role_id(kit_name, "senior_moderator"),
        get_role_id(kit_name, "tier_manager"), get_role_id(kit_name, "senior_tier_manager"),
        get_role_id(kit_name, "curator"), get_role_id(kit_name, "project_head"),
        get_role_id(kit_name, "network_manager"), get_role_id(kit_name, "tier_admin"),
        get_role_id(kit_name, "admin")
    ]
    return any(r in role_ids for r in allowed if r != 0)

async def check_tester_or_higher(inter: disnake.ApplicationCommandInteraction) -> bool:
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if is_tester_or_admin(inter.author, kit):
        return True
    await inter.response.send_message("❌ Команда доступна только тестерам и администраторам!", ephemeral=True)
    return False

async def check_admin_or_higher(inter: disnake.ApplicationCommandInteraction) -> bool:
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if is_admin_or_higher(inter.author, kit):
        return True
    await inter.response.send_message("❌ Команда доступна только администраторам и руководству!", ephemeral=True)
    return False

async def fetch_skin_bytes(player_ign: str):
    sources = [
        f"https://visage.surgeplay.com/full/340/{player_ign}",
        f"https://visage.surgeplay.com/avatar/180/{player_ign}",
        f"https://minotar.net/avatar/{player_ign}/150.png",
        "https://visage.surgeplay.com/full/340/MHF_Steve"
    ]
    async with aiohttp.ClientSession() as session:
        for src in sources:
            try:
                async with session.get(src, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        return await resp.read()
            except Exception as ex:
                logger.debug(f"Failed loading skin source {src}: {ex}")
                continue
    return None

def _draw_card_sync(skin_bytes, player_ign, tier_name, kit_name, tester_name, score):
    w, h = 900, 480
    card = Image.new("RGBA", (w, h), (10, 10, 10, 255))
    draw = ImageDraw.Draw(card)

    theme = get_kit_theme(kit_name)

    for y in range(h):
        r = int(10 + (y / h) * 12)
        g = int(10 + (y / h) * 6)
        b = int(10 + (y / h) * 2)
        draw.line([(0, y), (w, y)], fill=(r, g, b, 255))

    glow_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_overlay)
    glow_draw.ellipse([500, 30, 850, 350], fill=(theme["main"][0], theme["main"][1], theme["main"][2], 40))
    glow_draw.ellipse([50, 100, 350, 400], fill=(theme["glow"][0], theme["glow"][1], theme["glow"][2], 25))
    glow_overlay = glow_overlay.filter(ImageFilter.GaussianBlur(65))
    card = Image.alpha_composite(card, glow_overlay)
    draw = ImageDraw.Draw(card)

    draw.rounded_rectangle([14, 14, w - 14, h - 14], radius=22, outline=(theme["main"][0], theme["main"][1], theme["main"][2], 180), width=2)

    try:
        font_wm = ImageFont.truetype("arialbd.ttf", 16)
        font_subhead = ImageFont.truetype("segoeui.ttf", 15)
        font_tier = ImageFont.truetype("arialbd.ttf", 54)
        font_main = ImageFont.truetype("segoeuib.ttf", 19)
        font_small = ImageFont.truetype("segoeui.ttf", 15)
    except Exception:
        font_wm = font_tier = font_main = ImageFont.load_default()
        font_subhead = font_small = ImageFont.load_default()

    if skin_bytes:
        try:
            char_img = Image.open(io.BytesIO(skin_bytes)).convert("RGBA")
            if char_img.size[0] != char_img.size[1]:
                shadow = Image.new("RGBA", char_img.size, (0, 0, 0, 0))
                sh_draw = ImageDraw.Draw(shadow)
                sh_draw.ellipse([30, 290, 270, 335], fill=(0, 0, 0, 190))
                shadow = shadow.filter(ImageFilter.GaussianBlur(12))
                card.paste(shadow, (70, 80), shadow)
                card.paste(char_img, (70, 55), char_img)
            else:
                char_img = char_img.resize((150, 150), Image.Resampling.NEAREST)
                card.paste(char_img, (100, 130), char_img)
        except Exception as e:
            logger.warning(f"Error drawing skin image: {e}")

    draw.text((120, 385), player_ign, fill=(241, 245, 249), font=font_main)
    draw.text((130, 410), f"🗡️ {kit_name.upper()}", fill=theme["main"], font=font_small)

    center_x = 580
    draw.text((center_x - 45, 42), "PrizTiers", fill=(theme["main"][0], theme["main"][1], theme["main"][2], 140), font=font_wm)
    draw.text((center_x - 70, 75), "РЕЗУЛЬТАТ ТЕСТА", fill=theme["main"], font=font_subhead)
    draw.text((center_x - 45, 105), tier_name, fill=theme["main"], font=font_tier)

    draw.text((center_x - 35, 200), "Поединки", fill=(156, 163, 175), font=font_subhead)
    draw.text((center_x - 120, 230), f"{player_ign}   {score}   {tester_name}", fill=(241, 245, 249), font=font_main)

    draw.text((center_x - 25, 310), "Тестер", fill=(156, 163, 175), font=font_subhead)
    draw.text((center_x - 50, 340), tester_name, fill=(241, 245, 249), font=font_main)

    output = io.BytesIO()
    card.save(output, format="PNG")
    output.seek(0)
    return output

def _draw_profile_card_sync(skin_bytes, player_ign, server_name, ping, total_pts, tiers_dict, season_wins, custom_bg_path):
    w, h = 900, 500
    card = Image.new("RGBA", (w, h), (15, 15, 15, 255))

    if custom_bg_path and os.path.exists(custom_bg_path):
        try:
            bg_img = Image.open(custom_bg_path).convert("RGBA")
            bg_img = bg_img.resize((w, h), Image.Resampling.LANCZOS)
            overlay = Image.new("RGBA", (w, h), (0, 0, 0, 130))
            card.paste(bg_img, (0, 0))
            card = Image.alpha_composite(card, overlay)
        except Exception as e:
            logger.warning(f"Failed to load custom bg for profile: {e}")
            draw = ImageDraw.Draw(card)
            for y in range(h):
                r = int(12 + (y / h) * 15)
                g = int(12 + (y / h) * 10)
                b = int(18 + (y / h) * 25)
                draw.line([(0, y), (w, y)], fill=(r, g, b, 255))
    else:
        draw = ImageDraw.Draw(card)
        for y in range(h):
            r = int(12 + (y / h) * 15)
            g = int(12 + (y / h) * 10)
            b = int(18 + (y / h) * 25)
            draw.line([(0, y), (w, y)], fill=(r, g, b, 255))

    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle([14, 14, w - 14, h - 14], radius=22, outline=(168, 85, 247, 180), width=2)

    try:
        font_title = ImageFont.truetype("arialbd.ttf", 24)
        font_main = ImageFont.truetype("segoeuib.ttf", 18)
        font_small = ImageFont.truetype("segoeui.ttf", 15)
        font_badge = ImageFont.truetype("arialbd.ttf", 14)
    except Exception:
        font_title = font_main = font_small = font_badge = ImageFont.load_default()

    if skin_bytes:
        try:
            char_img = Image.open(io.BytesIO(skin_bytes)).convert("RGBA")
            if char_img.size[0] != char_img.size[1]:
                card.paste(char_img, (50, 70), char_img)
            else:
                char_img = char_img.resize((140, 140), Image.Resampling.NEAREST)
                card.paste(char_img, (70, 90), char_img)
        except Exception as e:
            logger.warning(f"Error drawing skin in profile: {e}")

    draw.text((230, 45), f"ПРОФИЛЬ ИГРОКА — {player_ign}", fill=(241, 245, 249), font=font_title)
    draw.text((230, 95), f"🌐 Сервер: {server_name}", fill=(203, 213, 225), font=font_main)
    draw.text((230, 125), f"📶 Пинг: {ping} ms", fill=(203, 213, 225), font=font_main)
    draw.text((230, 155), f"⭐ Всего очков: {total_pts} PTS", fill=(168, 85, 247), font=font_main)

    draw.text((230, 195), "🏆 Ранги по дисциплинам:", fill=(156, 163, 175), font=font_small)
    tier_strs = [f"{k}: {v}" for k, v in tiers_dict.items()]
    tiers_text = "  |  ".join(tier_strs) if tier_strs else "Нет активных рангов"
    draw.text((230, 220), tiers_text, fill=(241, 245, 249), font=font_main)

    draw.text((230, 270), "👑 Сезонные победы (Зал Славы):", fill=(156, 163, 175), font=font_small)
    if season_wins:
        bx = 230
        by = 300
        for s_num in season_wins:
            draw.rounded_rectangle([bx, by, bx + 110, by + 36], radius=8, fill=(168, 85, 247, 200), outline=(255, 255, 255, 220), width=1)
            draw.text((bx + 12, by + 8), f"🏆 Сезон #{s_num}", fill=(255, 255, 255), font=font_badge)
            bx += 125
            if bx > 750:
                bx = 230
                by += 45
    else:
        draw.text((230, 300), "Пока нет побед в сезонах", fill=(156, 163, 175), font=font_small)

    output = io.BytesIO()
    card.save(output, format="PNG")
    output.seek(0)
    return output

async def generate_profile_card_async(discord_id, member_name):
    ign, server_name, ping = db_get_player_info(discord_id)
    if ign == "Unknown":
        ign = member_name
    skin_bytes = await fetch_skin_bytes(ign)
    total_pts = calculate_total_points(discord_id)
    tiers_dict = db_get_player_tiers(discord_id)
    season_wins = db_get_season_wins(discord_id)
    custom_bg = db_get_player_background(discord_id)

    return await asyncio.to_thread(
        _draw_profile_card_sync, skin_bytes, ign, server_name, ping, total_pts, tiers_dict, season_wins, custom_bg
    )

async def generate_result_card_async(player_ign, tier_name, kit_name, tester_name, score="3-0"):
    skin_bytes = await fetch_skin_bytes(player_ign)
    return await asyncio.to_thread(_draw_card_sync, skin_bytes, player_ign, tier_name, kit_name, tester_name, score)

@bot.event
async def on_guild_channel_create(channel: disnake.abc.GuildChannel):
    save_channel_metadata_to_db(channel)

@bot.event
async def on_guild_channel_update(before: disnake.abc.GuildChannel, after: disnake.abc.GuildChannel):
    save_channel_metadata_to_db(after)

@bot.event
async def on_guild_channel_delete(channel: disnake.abc.GuildChannel):
    with get_db_connection(DB_FILE) as conn:
        conn.execute("DELETE FROM discord_channels_state WHERE channel_id = ?", (str(channel.id),))
        conn.commit()

@bot.event
async def on_message(message: disnake.Message):
    if not message.guild:
        return
    try:
        embeds_data = [e.to_dict() for e in message.embeds] if message.embeds else []
        attachments_data = [a.url for a in message.attachments] if message.attachments else []
        cat_name = message.channel.category.name if getattr(message.channel, "category", None) else ""
        with get_db_connection(ETERNAL_DB_FILE) as econn:
            econn.execute("""
                INSERT OR REPLACE INTO eternal_messages
                (message_id, guild_id, guild_name, channel_id, channel_name, category_name, author_id, author_name, is_bot, content, embeds_json, attachments_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(message.id),
                str(message.guild.id),
                message.guild.name,
                str(message.channel.id),
                message.channel.name,
                cat_name,
                str(message.author.id),
                str(message.author),
                1 if message.author.bot else 0,
                message.content or "",
                json.dumps(embeds_data, ensure_ascii=False),
                json.dumps(attachments_data, ensure_ascii=False),
                str(message.created_at)
            ))
            econn.commit()
    except Exception as e:
        logger.debug(f"Eternal message archive error: {e}")

    await bot.process_commands(message)

@bot.event
async def on_member_join(member: disnake.Member):
    kit = db_get_server_kit(member.guild.id)
    if kit:
        role_id = get_role_id(kit, "member")
        if role_id:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role)
                except Exception as e:
                    logger.warning(f"Failed to add member role to {member.id}: {e}")

def make_tester_embed(kit_name: str):
    return disnake.Embed(
        title=f"🛠️ Панель тестеров (Priz List) | Кит: {kit_name}",
        description=(
            "**Управление сменой и очередью:**\n"
            "• **🟢 Войти на смену** — начать работу.\n"
            "• **🛡️ Зайти помочь на смене** — подключиться к проверкам.\n"
            "• **⏸️ Выйти из смены** — завершить работу.\n"
            "• **🔔 Уведомления об очереди** — включить/выключить ЛС-оповещения при входе игрока в очередь."
        ),
        color=0x2b2d31
    )

async def notify_testers_about_player(kit_name: str, guild: disnake.Guild, player_ign: str, channel: disnake.TextChannel = None):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT discord_id FROM tester_kit_alerts WHERE kit = ? AND enabled = 1", (kit_name,))
        rows = cursor.fetchall()

    if not rows:
        return

    ch_id, _ = get_queue_channel_db(kit_name)
    queue_ch = guild.get_channel(ch_id) if ch_id else channel
    channel_link = f" ({queue_ch.mention})" if queue_ch else ""

    for (t_id_str,) in rows:
        try:
            t_id = int(t_id_str)
            member = guild.get_member(t_id)
            if not member:
                try:
                    member = await guild.fetch_member(t_id)
                except Exception:
                    member = None
            if member and is_tester_or_admin(member, kit_name):
                try:
                    await member.send(
                        f"🔵 **[{kit_name.upper()}]** Новый игрок зашел в очередь: `{player_ign}`!{channel_link}"
                    )
                except Exception as dm_err:
                    logger.debug(f"Failed to send DM queue alert to tester {t_id}: {dm_err}")
        except Exception as e:
            logger.debug(f"Failed verifying tester alert member {t_id_str}: {e}")


async def notify_ping_role_dm_queue_opened(kit_name: str, guild: disnake.Guild):
    role_id = get_role_id(kit_name, "ping")
    if not role_id:
        return
    role = guild.get_role(role_id)
    if not role:
        return

    ch_id, _ = get_queue_channel_db(kit_name)
    channel = guild.get_channel(ch_id) if ch_id else None
    channel_text = f" в канале {channel.mention}" if channel else ""

    dm_text = (
        f"🟢 **[{kit_name.upper()}]** Тестер открыл очередь{channel_text}, "
        f"вы можете зайти первым и протестироваться!"
    )

    for member in role.members:
        if member.bot:
            continue
        try:
            await member.send(dm_text)
        except Exception as e:
            logger.debug(f"Failed to send queue open DM to {member.id}: {e}")

async def notify_ping_role_dm_queue_closed(kit_name: str, guild: disnake.Guild):
    role_id = get_role_id(kit_name, "ping")
    if not role_id:
        return
    role = guild.get_role(role_id)
    if not role:
        return

    dm_text = (
        f"🔴 **[{kit_name.upper()}]** Последний тестер покинул смену, очередь закрылась."
    )

    for member in role.members:
        if member.bot:
            continue
        try:
            await member.send(dm_text)
        except Exception as e:
            logger.debug(f"Failed to send queue close DM to {member.id}: {e}")

async def notify_queue_status_change(kit_name: str, guild: disnake.Guild, is_open: bool):
    role_id = get_role_id(kit_name, "ping")
    ch_id, _ = get_queue_channel_db(kit_name)
    channel = guild.get_channel(ch_id) if ch_id else None

    if role_id:
        role = guild.get_role(role_id)
        if role:
            status_text = f"открылась для кита **{kit_name}**!" if is_open else f"закрылась для кита **{kit_name}**."
            ping_content = f"{role.mention} 🔔 Уведомление: Очередь {status_text}"
            if channel:
                try:
                    await channel.send(ping_content)
                except Exception as e:
                    logger.debug(f"Failed to send queue status ping in channel: {e}")
            else:
                for member in role.members:
                    try:
                        await member.send(f"🔔 Уведомление: Очередь {status_text}")
                    except Exception as e:
                        logger.debug(f"Failed to send DM notification to {member.id}: {e}")

async def update_queue_embed(kit_name: str, guild: disnake.Guild):
    q_data = get_queue_state(kit_name)
    old_status = q_data.get("was_open", False)
    new_status = q_data["is_open"]

    if old_status != new_status:
        q_data["was_open"] = new_status
        await notify_queue_status_change(kit_name, guild, new_status)

    save_queue_state(kit_name, q_data)

    theme = get_kit_theme(kit_name)
    color = theme["hex"] if q_data["is_open"] else 0xe74c3c
    embed = disnake.Embed(title="🟢 Очередь открыта" if q_data["is_open"] else "🔴 Очередь закрыта", color=color)

    testers_text = "\n".join([f"• **{guild.get_member(t).name if guild.get_member(t) else t}** (<@{t}>)" for t in q_data["active_testers"]]) or "Нет активных тестеров"
    embed.add_field(name="🛡️ Тиртестеры на смене", value=testers_text, inline=False)

    queue_list = q_data["queue"]
    q_lines = []
    for i, x in enumerate(queue_list[:10], start=1):
        user_tiers = db_get_player_tiers(x['user_id'])
        curr_tier = user_tiers.get(kit_name)
        tier_str = f" [{curr_tier}]" if curr_tier else ""
        q_lines.append(f"**{i}.** `{x['ign']}`{tier_str} • <@{x['user_id']}>")

    participants_text = "\n".join(q_lines) if q_lines else "Очередь пуста."
    embed.add_field(name=f"👥 В очереди ({len(queue_list)})", value=participants_text, inline=False)
    embed.description = ""

    msg = queue_messages.get(kit_name)
    if not msg:
        ch_id, m_id = get_queue_channel_db(kit_name)
        if ch_id and m_id:
            ch = guild.get_channel(ch_id) or bot.get_channel(ch_id)
            if ch:
                try:
                    msg = await ch.fetch_message(m_id)
                    queue_messages[kit_name] = msg
                except Exception as e:
                    logger.debug(f"Could not fetch saved queue message: {e}")

    if msg:
        try:
            await msg.edit(content=None, embed=embed, view=LiveQueueButtonsView(kit_name))
        except Exception as e:
            logger.warning(f"Failed to edit queue message embed for kit {kit_name}: {e}")

class PingRolePanelView(disnake.ui.View):
    def __init__(self, kit_name: str):
        super().__init__(timeout=None)
        self.kit_name = kit_name

    @disnake.ui.button(label="Получить роль", style=disnake.ButtonStyle.success, emoji="✅", custom_id="add_ping_role_btn")
    async def add_role(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        role_id = get_role_id(kit, "ping")
        role = inter.guild.get_role(role_id)
        if not role:
            return await inter.response.send_message("❌ Роль уведомлений не найдена на сервере!", ephemeral=True)

        if role in inter.author.roles:
            await inter.response.send_message("ℹ️ У вас уже есть эта роль!", ephemeral=True)
        else:
            try:
                await inter.author.add_roles(role)
                await inter.response.send_message("✅ Роль уведомлений успешно выдана!", ephemeral=True)
            except Exception as e:
                await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @disnake.ui.button(label="Снять роль", style=disnake.ButtonStyle.danger, emoji="❌", custom_id="remove_ping_role_btn")
    async def remove_role(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        role_id = get_role_id(kit, "ping")
        role = inter.guild.get_role(role_id)
        if not role:
            return await inter.response.send_message("❌ Роль уведомлений не найдена на сервере!", ephemeral=True)

        if role not in inter.author.roles:
            await inter.response.send_message("ℹ️ У вас нет этой роли!", ephemeral=True)
        else:
            try:
                await inter.author.remove_roles(role)
                await inter.response.send_message("✅ Роль уведомлений успешно снята!", ephemeral=True)
            except Exception as e:
                await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

class RolesSelectionView(disnake.ui.View):
    def __init__(self, kit_name: str):
        super().__init__(timeout=None)
        self.kit_name = kit_name

    async def _toggle_role(self, inter: disnake.MessageInteraction, role_key: str, role_name: str):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        role_id = get_role_id(kit, role_key)
        role = inter.guild.get_role(role_id)
        if not role:
            return await inter.response.send_message(f"❌ Роль `{role_name}` не найдена!", ephemeral=True)

        if role in inter.author.roles:
            await inter.author.remove_roles(role)
            await inter.response.send_message(f"❌ Роль `{role_name}` убрана.", ephemeral=True)
        else:
            await inter.author.add_roles(role)
            await inter.response.send_message(f"✅ Роль `{role_name}` выдана!", ephemeral=True)

    @disnake.ui.button(label="Новости", style=disnake.ButtonStyle.primary, emoji="🔊", custom_id="role_news_btn")
    async def toggle_news(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._toggle_role(inter, "news", "Новости")

    @disnake.ui.button(label="Опросы", style=disnake.ButtonStyle.success, emoji="🔔", custom_id="role_polls_btn")
    async def toggle_polls(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._toggle_role(inter, "polls", "Опросы")

    @disnake.ui.button(label="Матчмейкинг", style=disnake.ButtonStyle.secondary, emoji="⚔️", custom_id="role_mm_btn")
    async def toggle_matchmaking(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._toggle_role(inter, "matchmaking", "Матчмейкинг")

class AddUserToTicketModal(disnake.ui.Modal):
    def __init__(self, kit_name: str):
        self.kit_name = kit_name
        components = [
            disnake.ui.TextInput(label="ID или тег участника", placeholder="Например: 123456789012345678 или @user", custom_id="target_user", max_length=50)
        ]
        super().__init__(title="➕ Добавить участника в тикет", custom_id="add_user_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        raw_val = inter.text_values["target_user"].strip()
        kit = db_get_server_kit(inter.guild.id) or self.kit_name

        target_id_str = re.sub(r"\D", "", raw_val)
        if not target_id_str:
            return await inter.edit_original_response(content="❌ Не удалось распознать пользователя. Укажите корректный ID или упоминание.")

        target_member = inter.guild.get_member(int(target_id_str))
        if not target_member:
            try:
                target_member = await inter.guild.fetch_member(int(target_id_str))
            except Exception as e:
                logger.debug(f"Fetch member failed: {e}")

        if not target_member:
            return await inter.edit_original_response(content="❌ Участник с таким ID не найден на сервере!")

        allowed_role_keys = [
            "tester", "senior_tester", "head_tester", "moderator", "senior_moderator",
            "tier_manager", "senior_tier_manager", "curator", "project_head",
            "network_manager", "tier_admin", "admin", "network_owner"
        ]

        has_permission = False
        if is_network_owner(inter.author, kit) or is_tester_or_admin(inter.author, kit):
            member_role_ids = [r.id for r in target_member.roles]
            for r_key in allowed_role_keys:
                r_id = get_role_id(kit, r_key)
                if r_id and r_id in member_role_ids:
                    has_permission = True
                    break
            if target_member.id == inter.guild.owner_id or target_member.guild_permissions.administrator:
                has_permission = True

        if not has_permission:
            return await inter.edit_original_response(content="❌ Вы можете добавлять в тикет только пользователей со стафф-ролями!")

        try:
            await inter.channel.set_permissions(target_member, read_messages=True, send_messages=True)
            await inter.channel.send(f"➕ {inter.author.mention} добавил в тикет пользователя {target_member.mention}.")
            await inter.edit_original_response(content=f"✅ Участник {target_member.mention} успешно добавлен в тикет!")
        except Exception as e:
            await inter.edit_original_response(content=f"❌ Ошибка при добавлении участника: {e}")

class TestResultSelect(disnake.ui.Select):
    def __init__(self, kit_name: str, target_member: disnake.Member, tester: disnake.Member, is_high: bool):
        self.kit_name = kit_name
        self.target_member = target_member
        self.tester = tester
        self.is_high = is_high

        options = []
        if is_high:
            if is_head_tester_only(tester, kit_name):
                allowed_tiers = ["HT1", "RHT1", "LT1", "RLT1", "HT2", "RHT2", "LT2", "RLT2", "HT3"]
            elif is_senior_or_head_tester(tester, kit_name):
                allowed_tiers = ["HT3", "RLT2", "LT2"]
            else:
                allowed_tiers = ["HT3"]
        else:
            allowed_tiers = ["LT3", "HT4", "LT4", "HT5", "LT5"]

        for t in allowed_tiers:
            options.append(disnake.SelectOption(label=f"Ранг: {t}", value=t, description=f"Выдать тир {t} по киту {kit_name}"))

        super().__init__(placeholder="🏆 Выберите тир для выдачи игроку...", min_values=1, max_values=1, options=options)

    async def callback(self, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        tester = self.tester
        target_member = self.target_member
        chosen_tier = self.values[0]

        if self.is_high:
            if not is_senior_or_head_tester(tester, kit):
                return await inter.response.send_message("❌ Высокие тесты (от HT3 и выше) могут закрывать только Старшие и Главные тестеры!", ephemeral=True)
            if chosen_tier in ["HT1", "RHT1", "LT1", "RLT1", "HT2", "RHT2"] and not is_head_tester_only(tester, kit):
                return await inter.response.send_message("❌ Топовые тиры (HT2-HT1) может выдавать исключительно Главный тестер!", ephemeral=True)

        await inter.response.send_modal(ScoreModal(kit, target_member, tester, chosen_tier))

class ScoreModal(disnake.ui.Modal):
    def __init__(self, kit_name, target_member, tester, tier):
        self.kit_name = kit_name
        self.target_member = target_member
        self.tester = tester
        self.tier = tier
        components = [
            disnake.ui.TextInput(label="Счет матча", placeholder="Например: 3-0, 3-1, 3-2", custom_id="score_input", max_length=10, value="3-0")
        ]
        super().__init__(title="📊 Укажите счет поединка", custom_id="score_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        score = inter.text_values["score_input"]

        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        member = self.target_member
        tier_u = self.tier.upper()

        old_tiers = db_get_player_tiers(member.id)
        old_tier = old_tiers.get(kit, "None")

        db_save_tier(member.id, kit, tier_u, update_cooldown=True)
        db_increment_tester_test(self.tester.id, kit)

        ign, _, _ = db_get_player_info(member.id)
        if ign == "Unknown":
            ign = member.display_name
            db_save_player_info(member.id, ign, "Не указан", "Не указан")

        tester_ign, _, _ = db_get_player_info(self.tester.id)
        if tester_ign == "Unknown":
            tester_ign = self.tester.display_name

        db_log_match(member.id, ign, kit, old_tier, tier_u, score, self.tester.id, tester_ign)

        kit_roles = get_all_tier_role_ids(kit)
        role_id = kit_roles.get(tier_u)
        if role_id:
            role = inter.guild.get_role(role_id)
            if role:
                try:
                    for r_id in kit_roles.values():
                        old_r = inter.guild.get_role(r_id)
                        if old_r and old_r in member.roles:
                            await member.remove_roles(old_r)
                    await member.add_roles(role)
                except Exception as e:
                    logger.warning(f"Error managing roles for member {member.id}: {e}")

        theme = get_kit_theme(kit)
        card_bytes = await generate_result_card_async(ign, tier_u, kit, tester_ign, score)
        file = disnake.File(fp=card_bytes, filename="result.png")

        embed = disnake.Embed(
            title=f"🏆 Результат теста | {kit}",
            description=f"**Игрок:** {member.mention} (`{ign}`)\n**Ранг:** `{tier_u}`\n**Счет:** `{score}`\n**Тестер:** {self.tester.mention} (`{tester_ign}`)",
            color=theme["hex"]
        )
        embed.set_image(url="attachment://result.png")

        target_ch_id = get_result_channel_id(kit)
        dest_channel = inter.guild.get_channel(target_ch_id) if target_ch_id else inter.channel
        if not dest_channel:
            dest_channel = inter.channel

        await dest_channel.send(embed=embed, file=file)
        await inter.edit_original_response(content="✅ Ранг успешно выдан, карточка отправлена в канал результатов! Канал закрыется через 5 секунд.")

        await asyncio.sleep(5)
        try:
            await inter.channel.delete()
        except Exception as e:
            logger.warning(f"Failed deleting ticket channel: {e}")

class TicketActiveControlView(disnake.ui.View):
    def __init__(self, kit_name: str, target_member: disnake.Member, is_high: bool):
        super().__init__(timeout=None)
        self.kit_name = kit_name
        self.target_member = target_member
        self.is_high = is_high
        self.test_started = False

    @disnake.ui.button(label="Начать тест", style=disnake.ButtonStyle.green, emoji="▶️", custom_id="ticket_toggle_test_btn")
    async def toggle_test(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Только тестеры могут управлять тестом!", ephemeral=True)

        target = self.target_member
        if not target:
            for member in inter.channel.members:
                if not member.bot and not is_tester_or_admin(member, kit):
                    target = member
                    break
        if not target:
            return await inter.response.send_message("❌ Не удалось определить испытуемого игрока в этом канале.", ephemeral=True)

        if not self.test_started:
            self.test_started = True
            btn.label = "Завершить тест"
            btn.style = disnake.ButtonStyle.red
            btn.emoji = "⏸️"
            await inter.response.edit_message(view=self)
            await inter.followup.send(f"▶️ Тест начат тестером {inter.author.mention}. По завершении нажмите кнопку еще раз.", ephemeral=False)
        else:
            view = disnake.ui.View()
            view.add_item(TestResultSelect(kit, target, inter.author, self.is_high))
            await inter.response.send_message("🎯 Выберите итоговый тир игрока из выпадающего меню ниже:", view=view, ephemeral=True)

    @disnake.ui.button(label="Добавить участника", style=disnake.ButtonStyle.blurple, emoji="➕", custom_id="ticket_add_user_btn")
    async def add_user_btn(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Недостаточно прав для добавления участников!", ephemeral=True)
        await inter.response.send_modal(AddUserToTicketModal(kit))

    @disnake.ui.button(label="Закрыть (Игрок АФК / без КД)", style=disnake.ButtonStyle.gray, emoji="💤", custom_id="ticket_close_afk_btn")
    async def close_afk_btn(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Закрывать тикет могут только тестеры и администраторы!", ephemeral=True)

        await inter.response.send_message("💤 Тикет закрыт из-за АФК игрока (КД на тест не наложено). Канал будет удален через 3 секунды...", ephemeral=False)
        await asyncio.sleep(3)
        try:
            await inter.channel.delete()
        except Exception as e:
            logger.warning(f"Failed deleting AFK ticket channel: {e}")

class CloseTicketView(disnake.ui.View):
    def __init__(self, kit_name: str = "Beast"):
        super().__init__(timeout=None)
        self.kit_name = kit_name

    @disnake.ui.button(label="Закрыть тикет", style=disnake.ButtonStyle.red, emoji="🔒", custom_id="close_ticket_btn")
    async def close_ticket(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_admin_or_higher(inter.author, kit) and not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Закрывать тикеты могут только администраторы и тестеры!", ephemeral=True)

        await inter.response.send_message("🔒 Тикет закрывается и канал будет удален через 3 секунды...", ephemeral=True)
        await asyncio.sleep(3)
        try:
            await inter.channel.delete()
        except Exception as e:
            logger.warning(f"Failed deleting ticket channel: {e}")

    @disnake.ui.button(label="Добавить участника", style=disnake.ButtonStyle.blurple, emoji="➕", custom_id="support_add_user_btn")
    async def add_user_btn(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Недостаточно прав для добавления участников!", ephemeral=True)
        await inter.response.send_modal(AddUserToTicketModal(kit))

class SupportTicketView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="Жалоба", style=disnake.ButtonStyle.red, emoji="🚨", custom_id="t_report")
    async def report(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self.create_ticket(inter, "жалоба")

    @disnake.ui.button(label="Поддержка", style=disnake.ButtonStyle.blurple, emoji="🛠️", custom_id="t_sup")
    async def support(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self.create_ticket(inter, "поддержка")

    @disnake.ui.button(label="Заявка на тестера", style=disnake.ButtonStyle.green, emoji="📋", custom_id="t_tester")
    async def tester_apply(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self.create_ticket(inter, "заявка-тестер")

    @disnake.ui.button(label="Заявка в КП", style=disnake.ButtonStyle.gray, emoji="⚡", custom_id="t_kp")
    async def kp_apply(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self.create_ticket(inter, "заявка-кп")

    async def create_ticket(self, inter: disnake.MessageInteraction, category_type: str):
        await inter.response.defer(ephemeral=True)
        guild, user = inter.guild, inter.author
        kit = db_get_server_kit(guild.id) or "Beast"

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(read_messages=False),
            user: disnake.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        support_role_keys = [
            "helper", "moderator", "senior_moderator", "curator",
            "tier_manager", "senior_tier_manager", "project_head",
            "network_manager", "tier_admin", "admin", "network_owner"
        ]

        for r_key in support_role_keys:
            r_id = get_role_id(kit, r_key)
            if r_id:
                role_obj = guild.get_role(r_id)
                if role_obj:
                    overwrites[role_obj] = disnake.PermissionOverwrite(read_messages=True, send_messages=True)

        uid_str = str(user.id)
        safe_name = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]", "", user.name.lower())[:10] or "user"
        unique_suffix = f"{safe_name}-{uid_str[-4:]}-{random.randint(1000, 9999)}"
        channel_name = f"{category_type}-{unique_suffix}".lower()[:90]

        ch = await guild.create_text_channel(name=channel_name, overwrites=overwrites)

        embed = disnake.Embed(
            title=f"🎫 Тикет: {category_type.upper()}",
            description=f"Здравствуйте, {user.mention}! Опишите вашу проблему или вопрос. Администрация или тестеры ответят вам в ближайшее время.",
            color=0xa855f7
        )
        await ch.send(content=f"@here {user.mention}", embed=embed, view=CloseTicketView(kit))
        await ch.send(f"✅ Тикет успешно создан для {user.mention}!")
        await inter.edit_original_response(content=f"✅ Ваш тикет успешно создан: {ch.mention}")

class TestApplicationModal(disnake.ui.Modal):
    def __init__(self, kit_name: str):
        self.kit_name = kit_name
        components = [
            disnake.ui.TextInput(label="Игровой ник (IGN)", placeholder="Введите ваш ник в Minecraft (1 аккаунт = 1 ник)", custom_id="ign", max_length=32),
            disnake.ui.TextInput(label="На каком сервере играете?", placeholder="Примеры: PriZriT, aormio.ru", custom_id="server_name", max_length=50),
            disnake.ui.TextInput(label="Какой у вас пинг?", placeholder="Например: 45ms", custom_id="ping", max_length=10)
        ]
        super().__init__(title="📝 Регистрация и анкета на тест", custom_id="test_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        kit = db_get_server_kit(inter.guild.id) or self.kit_name

        discord_id = str(inter.author.id)
        input_ign = inter.text_values["ign"].strip()
        server_name = inter.text_values["server_name"].strip()
        ping = inter.text_values["ping"].strip()

        if not input_ign:
            return await inter.edit_original_response(content="❌ Игровой никнейм не может быть пустым!")

        if is_player_registered(discord_id):
            existing_ign, _, _ = db_get_player_info(discord_id)
            if existing_ign.lower() != input_ign.lower():
                return await inter.edit_original_response(
                    content=(
                        f"❌ За вашим аккаунтом уже закреплен никнейм **`{existing_ign}`** (1 аккаунт = 1 ник)!\n"
                        f"Чтобы сменить ник, используйте кнопку **Rename** (доступно раз в 15 дней)."
                    )
                )
            final_ign = existing_ign
            db_save_player_info(discord_id, final_ign, server_name, ping, username=inter.author.name, discord_tag=str(inter.author))
        else:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT discord_id FROM players WHERE LOWER(ign) = LOWER(?) AND discord_id != ?", (input_ign, discord_id))
                taken = cursor.fetchone()
                if taken:
                    return await inter.edit_original_response(
                        content=f"❌ Никнейм **`{input_ign}`** уже зарегистрирован другим игроком!"
                    )

            final_ign = input_ign
            db_save_player_info(discord_id, final_ign, server_name, ping, username=inter.author.name, discord_tag=str(inter.author))
            set_last_rename(discord_id)

        await update_all_guilds_nickname(inter.author.id, final_ign)

        role_id = get_role_id(kit, "whitelist")
        role_mention = ""
        if role_id:
            role = inter.guild.get_role(role_id)
            if role:
                role_mention = f" ({role.mention})"
                if role not in inter.author.roles:
                    try:
                        await inter.author.add_roles(role)
                    except Exception as e:
                        logger.warning(f"Failed adding whitelist role: {e}")

        await inter.edit_original_response(
            content=(
                f"✅ **Верификация и регистрация успешно пройдены!**\n"
                f"• Выдана роль **Whitelist** для кита **{kit}**{role_mention}.\n"
                f"• Ник: `{final_ign}` | Сервер: `{server_name}` | Пинг: `{ping}`\n"
                f"Теперь вы можете зайти в очередь через панель очереди, когда тестеры откроют смену."
            )
        )

class RenameModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(label="Новый игровой ник (IGN)", placeholder="Введите новый ник в Minecraft", custom_id="new_ign", max_length=32)
        ]
        super().__init__(title="✏️ Смена игрового никнейма (КД 15 дней)", custom_id="rename_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        discord_id = str(inter.author.id)
        new_ign = inter.text_values["new_ign"].strip()

        if not new_ign:
            return await inter.edit_original_response(content="❌ Новый никнейм не может быть пустым!")

        if not is_player_registered(discord_id):
            return await inter.edit_original_response(
                content="❌ Вы еще не зарегистрированы! Сначала пройдите регистрацию через кнопку **«Пройти тест»**."
            )

        current_ign, server_name, ping = db_get_player_info(discord_id)
        if current_ign.lower() == new_ign.lower():
            return await inter.edit_original_response(content=f"❌ У вас уже установлен никнейм **`{current_ign}`**!")

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT discord_id FROM players WHERE LOWER(ign) = LOWER(?) AND discord_id != ?", (new_ign, discord_id))
            taken = cursor.fetchone()
            if taken:
                return await inter.edit_original_response(content=f"❌ Никнейм **`{new_ign}`** уже занят другим игроком!")

        last_changed = get_last_rename(discord_id)
        now = datetime.now(timezone.utc)
        if last_changed:
            if last_changed.tzinfo is None:
                last_changed = last_changed.replace(tzinfo=timezone.utc)
            elapsed = now - last_changed
            cooldown = timedelta(days=15)
            if elapsed < cooldown:
                remaining = cooldown - elapsed
                days = remaining.days
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                return await inter.edit_original_response(
                    content=f"❌ Сменить никнейм можно раз в 15 дней! До следующей смены осталось: **{days} дн. {hours} ч. {minutes} мин.**"
                )

        db_save_player_info(discord_id, new_ign, server_name, ping, username=inter.author.name, discord_tag=str(inter.author))
        set_last_rename(discord_id)

        try:
            if inter.author.id != inter.guild.owner_id:
                await inter.author.edit(nick=new_ign)
        except Exception as e:
            logger.debug(f"Failed to update author nickname on current guild: {e}")

        await update_all_guilds_nickname(inter.author.id, new_ign)

        await inter.edit_original_response(
            content=f"✅ Никнейм успешно изменен с **`{current_ign}`** на **`{new_ign}`** на всех серверах!"
        )

class SelectPlayerModal(disnake.ui.Select):
    def __init__(self, queue_list, kit_name):
        self.kit_name = kit_name
        options = []
        for idx, item in enumerate(queue_list[:25]):
            options.append(disnake.SelectOption(
                label=f"#{idx+1} | {item['ign']}",
                value=str(item['user_id']),
                description=f"Игрок в очереди кита {kit_name}"
            ))
        super().__init__(placeholder="🎯 Выберите участника из очереди для теста...", min_values=1, max_values=1, options=options)

    async def callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_network_owner(inter.author, kit) and not is_tester_or_admin(inter.author, kit):
            return await inter.edit_original_response(content="❌ Доступно только тестерам и администраторам!")

        target_user_id = int(self.values[0])
        q_state = get_queue_state(kit)
        q = q_state["queue"]

        target_item = None
        for item in q:
            if item["user_id"] == target_user_id:
                target_item = item
                q.remove(item)
                break

        if not target_item:
            return await inter.edit_original_response(content="❌ Этот игрок уже вышел из очереди или был удален.")

        q_state["queue"] = q
        save_queue_state(kit, q_state)
        await update_queue_embed(kit, inter.guild)

        guild = inter.guild
        tester = inter.author
        target_member = guild.get_member(target_user_id)

        if not target_member:
            try:
                target_member = await guild.fetch_member(target_user_id)
            except Exception:
                target_member = None

        if not target_member:
            return await inter.edit_original_response(content="❌ Игрок не найден на сервере, но успешно удален из очереди.")

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(read_messages=False),
            tester: disnake.PermissionOverwrite(read_messages=True, send_messages=True),
            target_member: disnake.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        test_role_keys = [
            "tester", "senior_tester", "head_tester", "moderator", "senior_moderator",
            "tier_manager", "senior_tier_manager", "curator", "project_head",
            "network_manager", "tier_admin", "admin", "network_owner"
        ]
        for r_key in test_role_keys:
            r_id = get_role_id(kit, r_key)
            if r_id:
                role_obj = guild.get_role(r_id)
                if role_obj:
                    overwrites[role_obj] = disnake.PermissionOverwrite(read_messages=True, send_messages=True)

        safe_target_name = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]", "", target_member.name.lower())[:10] or "player"
        unique_ticket_name = f"тест-{safe_target_name}-{str(target_member.id)[-4:]}-{random.randint(1000,9999)}".lower()[:90]
        ch = await guild.create_text_channel(name=unique_ticket_name, overwrites=overwrites)

        theme = get_kit_theme(kit)
        embed = disnake.Embed(
            title=f"⚔️ Начало тестового поединка | Кит: {kit}",
            description=f"Тестер {tester.mention} вызвал на проверку игрока {target_member.mention} (`{target_item['ign']}`).\n\nИнформация (видно только тестеру):\n• Сервер: `{target_item['server']}`\n• Пинг: `{target_item['ping']}`",
            color=theme["hex"]
        )
        await ch.send(content=f"{tester.mention} {target_member.mention}", embed=embed, view=TicketActiveControlView(kit, target_member, is_high=False))
        await inter.edit_original_response(content=f"🎯 Выбран игрок `{target_item['ign']}`! Создан канал теста: {ch.mention}")

class SelectPlayerView(disnake.ui.View):
    def __init__(self, queue_list, kit_name):
        super().__init__(timeout=60)
        self.add_item(SelectPlayerModal(queue_list, kit_name))

class LiveQueueButtonsView(disnake.ui.View):
    def __init__(self, kit_name: str):
        super().__init__(timeout=None)
        self.kit_name = kit_name

    @disnake.ui.button(label="Войти в очередь", style=disnake.ButtonStyle.green, emoji="📥", custom_id="q_join")
    async def join_q(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        q_state = get_queue_state(kit)
        if not q_state["is_open"] or not q_state["active_testers"]:
            return await inter.response.send_message("❌ Очередь сейчас закрыта! Ни один тестер еще не зашел на смену.", ephemeral=True)

        if not is_network_owner(inter.author, kit) and is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Тестеры и администраторы не могут вставать в очередь!", ephemeral=True)

        on_cd, rem_str = check_test_cooldown(inter.author.id, kit)
        if on_cd and not is_network_owner(inter.author, kit):
            return await inter.response.send_message(f"⏳ Вы недавно проходили тест по киту **{kit}**! Повторный тест доступен раз в 14 дней.\nОсталось: **{rem_str}**.", ephemeral=True)

        ign, server_name, ping = db_get_player_info(inter.author.id)
        if not is_player_registered(inter.author.id) or ign == "Unknown" or not server_name or server_name == "Не указан":
            await inter.response.send_modal(TestApplicationModal(kit))
        else:
            role_id = get_role_id(kit, "whitelist")
            if role_id:
                role = inter.guild.get_role(role_id)
                if role and role not in inter.author.roles:
                    try:
                        await inter.author.add_roles(role)
                    except Exception as e:
                        logger.warning(f"Failed to add whitelist role: {e}")

            q = q_state["queue"]
            if not any(x["user_id"] == inter.author.id for x in q):
                q.append({"user_id": inter.author.id, "ign": ign, "server": server_name, "ping": ping})
                q_state["queue"] = q
                save_queue_state(kit, q_state)
                await update_queue_embed(kit, inter.guild)
                asyncio.create_task(notify_testers_about_player(kit, inter.guild, ign, inter.channel))

            await inter.response.send_message(
                content=(
                    f"✅ **Вы успешно вошли в очередь!**\n"
                    f"• Ник: `{ign}` | Сервер: `{server_name}` | Пинг: `{ping}`"
                ),
                ephemeral=True
            )

    @disnake.ui.button(label="Выйти из очереди", style=disnake.ButtonStyle.red, emoji="📤", custom_id="q_leave")
    async def leave_q(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        q_state = get_queue_state(kit)
        q = q_state["queue"]
        user_id = inter.author.id
        found = False
        for item in q:
            if item["user_id"] == user_id:
                q.remove(item)
                found = True
                break
        if not found:
            return await inter.response.send_message("❌ Вас нет в текущей очереди!", ephemeral=True)
        q_state["queue"] = q
        save_queue_state(kit, q_state)
        await inter.response.send_message("📤 Вы вышли из очереди.", ephemeral=True)
        await update_queue_embed(kit, inter.guild)

    @disnake.ui.button(label="Мое место", style=disnake.ButtonStyle.blurple, emoji="📊", custom_id="q_pos")
    async def queue_pos(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        q_state = get_queue_state(kit)
        q = q_state["queue"]
        user_id = inter.author.id
        for idx, item in enumerate(q, start=1):
            if item["user_id"] == user_id:
                return await inter.response.send_message(f"📊 Ваше место в очереди: **#{idx}** из {len(q)}", ephemeral=True)
        await inter.response.send_message("❌ Вас нет в активной очереди.", ephemeral=True)

    @disnake.ui.button(label="Выбрать из очереди", style=disnake.ButtonStyle.gray, emoji="👥", custom_id="q_take")
    async def take_participant(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_network_owner(inter.author, kit) and not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Эта кнопка доступна только тиртестерам и администраторам!", ephemeral=True)
        q_state = get_queue_state(kit)
        q = q_state["queue"]
        if not q:
            return await inter.response.send_message("❌ Очередь пуста!", ephemeral=True)
        await inter.response.send_message("🎯 Выберите участника из списка ниже:", view=SelectPlayerView(q, kit), ephemeral=True)

class TesterControlView(disnake.ui.View):
    def __init__(self, kit_name: str):
        super().__init__(timeout=None)
        self.kit_name = kit_name

    @disnake.ui.button(label="Войти на смену", style=disnake.ButtonStyle.green, emoji="🟢", custom_id="t_start")
    async def shift_start(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_network_owner(inter.author, kit) and not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Только тестеры могут заступать на смену!", ephemeral=True)

        q_state = get_queue_state(kit)
        if inter.author.id in q_state["active_testers"]:
            return await inter.response.send_message("ℹ️ Вы уже находитесь на смене!", ephemeral=True)

        was_empty = len(q_state["active_testers"]) == 0
        q_state["active_testers"].append(inter.author.id)
        q_state["is_open"] = True
        save_queue_state(kit, q_state)

        try:
            await inter.message.edit(content=None, embed=make_tester_embed(kit), view=self)
        except Exception:
            pass

        await inter.response.send_message("🟢 Вы заступили на смену!", ephemeral=True)
        await update_queue_embed(kit, inter.guild)

        if was_empty:
            asyncio.create_task(notify_ping_role_dm_queue_opened(kit, inter.guild))

    @disnake.ui.button(label="Зайти помочь на смене", style=disnake.ButtonStyle.blurple, emoji="🛡️", custom_id="t_help")
    async def shift_help(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_network_owner(inter.author, kit) and not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Только тестеры могут помогать на смене!", ephemeral=True)

        q_state = get_queue_state(kit)
        if inter.author.id in q_state["active_testers"]:
            return await inter.response.send_message("ℹ️ Вы уже находитесь на смене!", ephemeral=True)

        was_empty = len(q_state["active_testers"]) == 0
        q_state["active_testers"].append(inter.author.id)
        q_state["is_open"] = True
        save_queue_state(kit, q_state)

        try:
            await inter.message.edit(content=None, embed=make_tester_embed(kit), view=self)
        except Exception:
            pass

        await inter.response.send_message("🛡️ Вы подключились к помощи на смене!", ephemeral=True)
        await update_queue_embed(kit, inter.guild)

        if was_empty:
            asyncio.create_task(notify_ping_role_dm_queue_opened(kit, inter.guild))

    @disnake.ui.button(label="Выйти из смены", style=disnake.ButtonStyle.red, emoji="⏸️", custom_id="t_pause")
    async def shift_pause(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_network_owner(inter.author, kit) and not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Только тестеры могут выходить со смены!", ephemeral=True)

        q_state = get_queue_state(kit)
        if inter.author.id not in q_state["active_testers"]:
            return await inter.response.send_message("ℹ️ Вы сейчас не на смене!", ephemeral=True)

        q_state["active_testers"].remove(inter.author.id)

        is_now_empty = len(q_state["active_testers"]) == 0
        removed_participants = []

        if is_now_empty:
            q_state["is_open"] = False
            removed_participants = list(q_state["queue"])
            q_state["queue"] = []

        save_queue_state(kit, q_state)

        try:
            await inter.message.edit(content=None, embed=make_tester_embed(kit), view=self)
        except Exception:
            pass

        await inter.response.send_message("⏸️ Вы вышли из смены.", ephemeral=True)
        await update_queue_embed(kit, inter.guild)

        if is_now_empty:
            asyncio.create_task(notify_ping_role_dm_queue_closed(kit, inter.guild))
            for p in removed_participants:
                pid = p.get("user_id")
                try:
                    member = inter.guild.get_member(pid) or await inter.guild.fetch_member(pid)
                    if member:
                        await member.send(f"❌ Очередь кита **{kit.upper()}** была закрыта, так как последний тестер покинул смену. Вы были удалены из очереди.")
                except Exception as ex:
                    logger.debug(f"Failed to send DM to participant {pid}: {ex}")

    @disnake.ui.button(label="Уведомления об очереди", style=disnake.ButtonStyle.secondary, emoji="🔔", custom_id="t_toggle_alerts")
    async def toggle_queue_alerts(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        if not is_network_owner(inter.author, kit) and not is_tester_or_admin(inter.author, kit):
            return await inter.response.send_message("❌ Доступно только тестерам!", ephemeral=True)

        tester_id = str(inter.author.id)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT enabled FROM tester_kit_alerts WHERE kit = ? AND discord_id = ?", (kit, tester_id))
            row = cursor.fetchone()
            current_state = int(row[0]) if row else 0

            new_state = 0 if current_state == 1 else 1
            cursor.execute("""
                INSERT INTO tester_kit_alerts (kit, discord_id, enabled) VALUES (?, ?, ?)
                ON CONFLICT(kit, discord_id) DO UPDATE SET enabled = ?
            """, (kit, tester_id, new_state, new_state))
            conn.commit()

        if new_state == 1:
            await inter.response.send_message(
                f"🔔 **Уведомления об очереди ({kit.upper()}) ВКЛЮЧЕНЫ!** Теперь бот будет отправлять вам сообщение в ЛС каждый раз, когда кто-то зайдет в очередь на этот кит.",
                ephemeral=True
            )
        else:
            await inter.response.send_message(
                f"🔕 **Уведомления об очереди ({kit.upper()}) ВЫКЛЮЧЕНЫ!** Вы больше не будете получать ЛС-оповещения по этому киту.",
                ephemeral=True
            )

class TestPanelView(disnake.ui.View):
    def __init__(self, kit_name: str):
        super().__init__(timeout=None)
        self.kit_name = kit_name

    @disnake.ui.button(label="Пройти тест", style=disnake.ButtonStyle.green, emoji="🏆", custom_id="t_test")
    async def test_btn(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        await inter.response.send_modal(TestApplicationModal(kit))

    @disnake.ui.button(label="Мой профиль", style=disnake.ButtonStyle.grey, emoji="📊", custom_id="p_view")
    async def profile_view(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        card_bytes = await generate_profile_card_async(inter.author.id, inter.author.display_name)
        file = disnake.File(fp=card_bytes, filename="profile.png")
        await inter.edit_original_response(file=file)

    @disnake.ui.button(label="Rename", style=disnake.ButtonStyle.blurple, emoji="✏️", custom_id="p_rename")
    async def rename_btn(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        discord_id = str(inter.author.id)
        if not is_player_registered(discord_id):
            return await inter.response.send_message(
                "❌ Вы еще не зарегистрированы в системе! Сначала нажмите кнопку **«Пройти тест»** и привяжите свой ник.",
                ephemeral=True
            )

        last_changed = get_last_rename(discord_id)
        if last_changed:
            now = datetime.now(timezone.utc)
            if last_changed.tzinfo is None:
                last_changed = last_changed.replace(tzinfo=timezone.utc)
            elapsed = now - last_changed
            cooldown = timedelta(days=15)
            if elapsed < cooldown:
                remaining = cooldown - elapsed
                days = remaining.days
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                return await inter.response.send_message(
                    f"❌ Сменить никнейм можно раз в 15 дней! До следующей смены осталось: **{days} дн. {hours} ч. {minutes} мин.**",
                    ephemeral=True
                )

        await inter.response.send_modal(RenameModal())

class HighTestPanelView(disnake.ui.View):
    def __init__(self, kit_name: str):
        super().__init__(timeout=None)
        self.kit_name = kit_name

    @disnake.ui.button(label="Пройти Высокий Тест", style=disnake.ButtonStyle.blurple, emoji="🔥", custom_id="ht_pass")
    async def pass_high_test(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or self.kit_name
        user_tiers = db_get_player_tiers(inter.author.id)
        curr_tier = user_tiers.get(kit)

        allowed_high_check = ["LT3", "HT3", "RLT2", "LT2", "RHT2", "HT2", "RLT1", "LT1", "RHT1", "HT1"]
        if not is_network_owner(inter.author, kit) and (not curr_tier or curr_tier not in allowed_high_check):
            return await inter.response.send_message("❌ Высокий тест доступен только игрокам с рангом от **LT3** и выше!", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        guild = inter.guild
        user = inter.author

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(read_messages=False),
            user: disnake.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        test_role_keys = [
            "tester", "senior_tester", "head_tester", "moderator", "senior_moderator",
            "tier_manager", "senior_tier_manager", "curator", "project_head",
            "network_manager", "tier_admin", "admin", "network_owner"
        ]
        for r_key in test_role_keys:
            r_id = get_role_id(kit, r_key)
            if r_id:
                role_obj = guild.get_role(r_id)
                if role_obj:
                    overwrites[role_obj] = disnake.PermissionOverwrite(read_messages=True, send_messages=True)

        safe_uname = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]", "", user.name.lower())[:10] or "user"
        unique_ht_name = f"высокий-тест-{safe_uname}-{str(user.id)[-4:]}-{random.randint(1000,9999)}".lower()[:90]
        ch = await guild.create_text_channel(name=unique_ht_name, overwrites=overwrites)

        theme = get_kit_theme(kit)
        embed = disnake.Embed(
            title=f"🔥 Высокий тест | Кит: {kit}",
            description=f"Игрок {user.mention} открыл тикет для прохождения высокого теста.\nТестеры могут взять этот тест в работу.",
            color=theme["hex"]
        )
        await ch.send(content=f"@here {user.mention}", embed=embed, view=TicketActiveControlView(kit, user, is_high=True))
        await inter.edit_original_response(content=f"✅ Тикет успешно создан: {ch.mention}")

    @disnake.ui.button(label="Мой профиль", style=disnake.ButtonStyle.grey, emoji="📊", custom_id="ht_profile")
    async def profile_view(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        card_bytes = await generate_profile_card_async(inter.author.id, inter.author.display_name)
        file = disnake.File(fp=card_bytes, filename="profile.png")
        await inter.edit_original_response(file=file)

class RestoreChannelsView(disnake.ui.View):
    def __init__(self, guild_id: str, snapshot_id: int):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.snapshot_id = snapshot_id

    @disnake.ui.button(label="Востановить пропавшие каналы", style=disnake.ButtonStyle.green, emoji="♻️")
    async def restore_channels_btn(self, btn: disnake.ui.Button, inter: disnake.MessageInteraction):
        kit = db_get_server_kit(inter.guild.id) or "Beast"
        if not is_network_owner(inter.author, kit):
            return await inter.response.send_message("❌ Эту кнопку может нажимать исключительно Владелец сети!", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        guild = inter.guild

        with get_db_connection(ETERNAL_DB_FILE) as econn:
            ecursor = econn.cursor()
            ecursor.execute("""
                SELECT channel_id, category_name, name, channel_type, topic, position, overwrites_json
                FROM eternal_channels_archive
                WHERE guild_id = ? AND snapshot_time = (
                    SELECT created_at FROM eternal_snapshots_meta WHERE id = ?
                )
            """, (str(guild.id), self.snapshot_id))
            archived_channels = ecursor.fetchall()

        if not archived_channels:
            return await inter.edit_original_response(content="❌ Для этого сервера не найдено каналов в выбранном снимке.")

        existing_channel_ids = {str(ch.id) for ch in guild.channels}
        existing_channel_names = {(ch.name.lower(), str(ch.type)) for ch in guild.channels}
        restored_count = 0

        for ch_id, cat_name, name, ch_type, topic, pos, ow_json in archived_channels:
            if ch_id in existing_channel_ids or (name.lower(), ch_type) in existing_channel_names:
                continue

            if "category" in ch_type:
                continue

            target_category = None
            if cat_name:
                target_category = disnake.utils.get(guild.categories, name=cat_name)
                if not target_category:
                    try:
                        target_category = await guild.create_category(name=cat_name)
                    except Exception:
                        target_category = None

            overwrites = {}
            try:
                ow_list = json.loads(ow_json) if ow_json else []
                for ow in ow_list:
                    t_id = int(ow["target_id"])
                    target_obj = guild.get_role(t_id) if ow["target_type"] == "role" else guild.get_member(t_id)
                    if target_obj:
                        allow_perm = disnake.Permissions(ow["allow"])
                        deny_perm = disnake.Permissions(ow["deny"])
                        overwrites[target_obj] = disnake.PermissionOverwrite.from_pair(allow_perm, deny_perm)
            except Exception as e:
                logger.debug(f"Error parsing overwrites on restore: {e}")

            try:
                if "text" in ch_type:
                    await guild.create_text_channel(
                        name=name,
                        category=target_category,
                        topic=topic or None,
                        overwrites=overwrites
                    )
                    restored_count += 1
                elif "voice" in ch_type:
                    await guild.create_voice_channel(
                        name=name,
                        category=target_category,
                        overwrites=overwrites
                    )
                    restored_count += 1
            except Exception as e:
                logger.warning(f"Failed restoring channel {name}: {e}")

        sync_all_guilds_channels_state()
        await inter.edit_original_response(
            content=f"✅ Восстановление завершено! Восстановлено пропавших каналов: **{restored_count}**."
        )

async def background_auto_updater():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(300)
        try:
            sync_all_guilds_channels_state()

            for kit in KITS:
                for guild in bot.guilds:
                    g_kit = db_get_server_kit(guild.id)
                    if g_kit == kit:
                        await update_queue_embed(kit, guild)

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT guild_id, channel_id, message_id, lb_type FROM active_leaderboards")
                lbs = cursor.fetchall()

            for guild_id, channel_id, message_id, lb_type in lbs:
                try:
                    guild = bot.get_guild(int(guild_id))
                    if not guild:
                        with get_db_connection() as conn:
                            conn.execute("DELETE FROM active_leaderboards WHERE guild_id = ? AND lb_type = ?", (guild_id, lb_type))
                            conn.commit()
                        continue

                    channel = guild.get_channel(int(channel_id))
                    if not channel:
                        with get_db_connection() as conn:
                            conn.execute("DELETE FROM active_leaderboards WHERE guild_id = ? AND lb_type = ?", (guild_id, lb_type))
                            conn.commit()
                        continue

                    try:
                        msg = await channel.fetch_message(int(message_id))
                    except Exception:
                        with get_db_connection() as conn:
                            conn.execute("DELETE FROM active_leaderboards WHERE guild_id = ? AND lb_type = ?", (guild_id, lb_type))
                            conn.commit()
                        continue

                    kit = db_get_server_kit(int(guild_id)) or "Beast"
                    theme = get_kit_theme(kit)

                    if lb_type == "players":
                        with get_db_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("SELECT discord_id, tier FROM user_tiers WHERE kit = ?", (kit,))
                            rows = cursor.fetchall()
                        user_scores = []
                        for discord_id, tier in rows:
                            pts = TIER_POINTS.get(tier, 0)
                            ign, _, _ = db_get_player_info(discord_id)
                            user_scores.append({"discord_id": discord_id, "ign": ign, "tier": tier, "points": pts})

                        user_scores.sort(key=lambda x: x["points"], reverse=True)
                        top_players = user_scores[:10]

                        embed = disnake.Embed(title=f"👑 Таблица лидеров — Кит: {kit}", color=theme["hex"], timestamp=datetime.now(timezone.utc))
                        if not top_players:
                            embed.description = "Пока нет данных о рангах в этом ките."
                        else:
                            desc_lines = []
                            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                            for idx, p in enumerate(top_players):
                                medal = medals[idx] if idx < len(medals) else f"`#{idx+1}`"
                                desc_lines.append(f"{medal} **{p['ign']}** — Ранг: `{p['tier']}` | Очки: **{p['points']} PTS** (<@{p['discord_id']}>)")
                            embed.description = "\n".join(desc_lines)
                        embed.set_footer(text="Priz Tiers • Автоматическое обновление каждые 5 минут")
                        await msg.edit(embed=embed)

                    elif lb_type == "testers":
                        with get_db_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("SELECT discord_id, test_count FROM tester_stats WHERE kit = ? ORDER BY test_count DESC LIMIT 10", (kit,))
                            tester_rows = cursor.fetchall()

                        embed = disnake.Embed(title=f"🏆 Лучшие тестеры месяца — Кит: {kit}", color=theme["hex"], timestamp=datetime.now(timezone.utc))
                        if not tester_rows:
                            embed.description = "В этом месяце тестеры еще не провели тестов."
                        else:
                            desc_lines = []
                            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                            for idx, (t_id, count) in enumerate(tester_rows):
                                medal = medals[idx] if idx < len(medals) else f"`#{idx+1}`"
                                member_obj = guild.get_member(int(t_id))
                                name = member_obj.display_name if member_obj else f"ID: {t_id}"
                                desc_lines.append(f"{medal} **{name}** — Проведено тестов: **{count}** (<@{t_id}>)")
                            embed.description = "\n".join(desc_lines)
                        embed.set_footer(text="Priz Tiers • Автоматическое обновление каждые 5 минут")
                        await msg.edit(embed=embed)
                except Exception as ex:
                    logger.error(f"Error in background leaderboard update for guild {guild_id}: {ex}")
        except Exception as e:
            logger.error(f"Error in background auto updater main loop: {e}")

@bot.event
async def on_ready():
    logger.info(f"🚀 Бот {bot.user} запущен и готов к работе!")
    sync_all_guilds_channels_state()

    bot.add_view(LiveQueueButtonsView("Beast"))
    bot.add_view(TesterControlView("Beast"))
    bot.add_view(TestPanelView("Beast"))
    bot.add_view(HighTestPanelView("Beast"))
    bot.add_view(CloseTicketView("Beast"))
    bot.add_view(SupportTicketView())
    bot.add_view(TicketActiveControlView("Beast", None, False))
    bot.add_view(PingRolePanelView("Beast"))
    bot.add_view(RolesSelectionView("Beast"))

    bot.loop.create_task(background_auto_updater())

@bot.event
async def on_slash_command_error(inter: disnake.ApplicationCommandInteraction, error: Exception):
    if isinstance(error, commands.CheckFailure):
        return
    cmd_name = inter.application_command.name if inter.application_command else "unknown"
    logger.error(f"❌ Ошибка в слэш-команде '{cmd_name}': {error}")
    if not inter.response.is_done():
        await inter.response.send_message("❌ Произошла непредвиденная ошибка при выполнении команды.", ephemeral=True)
    else:
        try:
            await inter.followup.send("❌ Произошла непредвиденная ошибка при выполнении команды.", ephemeral=True)
        except Exception as e:
            logger.debug(f"Failed sending error followup: {e}")

param_tier_low = commands.Param(choices=["LT5", "HT5", "LT4", "HT4", "LT3"])
param_tier_high = commands.Param(choices=["HT3", "RLT2", "LT2", "RHT2", "HT2", "RLT1", "LT1", "RHT1", "HT1"])

@bot.slash_command(name="history", description="Посмотреть историю поединков и тестов игрока")
async def history_cmd(inter: disnake.ApplicationCommandInteraction, member: disnake.Member = commands.Param(default=None, description="Участник")):
    target = member or inter.author
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT kit, old_tier, new_tier, score, tester_ign, timestamp
            FROM match_history
            WHERE discord_id = ?
            ORDER BY id DESC LIMIT 10
        """, (str(target.id),))
        rows = cursor.fetchall()

    ign, _, _ = db_get_player_info(target.id)
    if ign == "Unknown":
        ign = target.display_name

    embed = disnake.Embed(
        title=f"📜 История поединков — {ign}",
        color=0xa855f7,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=target.display_avatar.url)

    if not rows:
        embed.description = "У этого игрока пока нет записанных поединков."
    else:
        lines = []
        for kit, old_t, new_t, score, t_ign, ts in rows:
            date_str = ts[:10] if ts else ""
            lines.append(f"• **[{kit.upper()}]** `{old_t}` ➔ `{new_t}` | Счет: `{score}` (Тестер: `{t_ign}`) • *{date_str}*")
        embed.description = "\n".join(lines)

    embed.set_footer(text=f"Discord ID: {target.id}")
    await inter.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(name="vs", description="Сравнить двух игроков между собой")
async def vs_cmd(
    inter: disnake.ApplicationCommandInteraction,
    player1: disnake.Member = commands.Param(description="Первый игрок"),
    player2: disnake.Member = commands.Param(description="Второй игрок")
):
    pts1 = calculate_total_points(player1.id)
    pts2 = calculate_total_points(player2.id)

    ign1, s1, p1 = db_get_player_info(player1.id)
    ign2, s2, p2 = db_get_player_info(player2.id)
    if ign1 == "Unknown": ign1 = player1.display_name
    if ign2 == "Unknown": ign2 = player2.display_name

    tiers1 = db_get_player_tiers(player1.id)
    tiers2 = db_get_player_tiers(player2.id)

    embed = disnake.Embed(
        title=f"⚔️ Сравнение игроков: {ign1} vs {ign2}",
        color=0xa855f7,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(
        name=f"👤 {ign1}",
        value=f"• **Очки:** `{pts1} PTS`\n• **Сервер:** `{s1}`\n• **Пинг:** `{p1} ms`\n• **Beast:** `{tiers1.get('Beast', 'Нет')}`\n• **Mace:** `{tiers1.get('Mace', 'Нет')}`\n• **Carts:** `{tiers1.get('Carts', 'Нет')}`",
        inline=True
    )
    embed.add_field(
        name=f"👤 {ign2}",
        value=f"• **Очки:** `{pts2} PTS`\n• **Сервер:** `{s2}`\n• **Пинг:** `{p2} ms`\n• **Beast:** `{tiers2.get('Beast', 'Нет')}`\n• **Mace:** `{tiers2.get('Mace', 'Нет')}`\n• **Carts:** `{tiers2.get('Carts', 'Нет')}`",
        inline=True
    )
    embed.set_footer(text="Priz Tiers • Сравнение бойцов")
    await inter.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(name="set_fon", description="Установить кастомный фон профиля для игрока (Только для Владельца сети)", default_member_permissions=disnake.Permissions(administrator=True))
async def set_fon_cmd(
    inter: disnake.ApplicationCommandInteraction,
    member: disnake.Member = commands.Param(description="Участник, которому устанавливается фон"),
    image: disnake.Attachment = commands.Param(description="Картинка для фона (вложение)")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    if not image.content_type or not image.content_type.startswith("image/"):
        return await inter.response.send_message("❌ Прикрепленный файл должен быть изображением!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    try:
        img_bytes = await image.read()
        file_path = os.path.join(BG_DIR, f"{member.id}.png")
        with open(file_path, "wb") as f:
            f.write(img_bytes)

        db_set_player_background(str(member.id), file_path)
        await inter.edit_original_response(content=f"✅ Кастомный фон для игрока {member.mention} успешно установлен! Теперь в `/profile` будет использоваться это изображение.")
    except Exception as e:
        logger.error(f"Error in /set_fon: {e}")
        await inter.edit_original_response(content=f"❌ Ошибка при установке фона: {e}")

@bot.slash_command(name="season_end", description="Завершить текущий сезон, выдать роли победителям и начать новый (Только для Владельца)", default_member_permissions=disnake.Permissions(administrator=True))
async def season_end_cmd(
    inter: disnake.ApplicationCommandInteraction,
    winner: disnake.Member = commands.Param(description="Победитель сезона (1 место)")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    current_season = db_get_current_season()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO player_season_wins (discord_id, season_number) VALUES (?, ?)
        """, (str(winner.id), current_season))
        conn.commit()

    role_name = f"Победитель сезона №{current_season}"
    guild = inter.guild
    role = disnake.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(name=role_name, color=disnake.Color(0xa855f7), reason=f"Победитель сезона {current_season}")
        except Exception as e:
            logger.warning(f"Failed to create season role: {e}")

    if role:
        try:
            await winner.add_roles(role)
        except Exception as e:
            logger.warning(f"Failed to assign season role: {e}")

    next_season = current_season + 1
    db_set_current_season(next_season)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_tiers")
        conn.commit()

    embed = disnake.Embed(
        title=f"🎉 Итоги Сезона #{current_season} подведены!",
        description=f"Победителем текущего сезона стал {winner.mention} (`{winner.display_name}`)!\n\n• Ему навсегда присвоена роль **`{role_name}`**.\n• Цифра сезона навсегда зафиксирована на его персональном фоне профиля в `/profile`.\n\n🚀 **Сезон #{next_season} официально открыт!** Все тиры сброшены, ладдер чист.",
        color=0xa855f7,
        timestamp=datetime.now(timezone.utc)
    )
    await inter.channel.send(embed=embed)
    await inter.edit_original_response(content=f"✅ Сезон #{current_season} успешно завершен, победитель награжден, запущен Сезон #{next_season}!")

@bot.slash_command(name="save", description="Создать или восстановить сохранение в слотах 1-20 (Только для Владельца сети)", default_member_permissions=disnake.Permissions(administrator=True))
async def save_cmd(
    inter: disnake.ApplicationCommandInteraction,
    slot: int = commands.Param(default=None, ge=1, le=20, description="Номер слота (1-20) для восстановления. Оставьте пустым для создания нового сохранения.")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    await inter.response.defer(ephemeral=True)
    try:
        sync_all_guilds_channels_state()

        if slot is not None:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT file_path, timestamp FROM manual_backups WHERE slot_id = ?", (slot,))
                row = cursor.fetchone()

            if not row or not os.path.exists(row[0]):
                return await inter.edit_original_response(content=f"❌ Слот **#{slot}** пуст или файл сохранения не найден!")

            backup_path, ts = row
            with sqlite3.connect(backup_path) as src_conn:
                with get_db_connection(DB_FILE) as dst_conn:
                    src_conn.backup(dst_conn)

            init_db()
            for k in KITS:
                await update_queue_embed(k, inter.guild)

            with open(DB_FILE, "rb") as bf:
                restored_bytes = bf.read()

            file_obj = disnake.File(fp=io.BytesIO(restored_bytes), filename=f"restored_slot_{slot}.db")
            return await inter.edit_original_response(
                content=f"♻️ **База данных успешно восстановлена из слота #{slot}** (от `{ts}`)! Все тиры, игроки и настройки возвращены:",
                file=file_obj
            )

        with open(DB_FILE, "rb") as f:
            db_bytes = f.read()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM manual_backups")
            count = cursor.fetchone()[0]
            slot_id = (count % 20) + 1

            file_path = os.path.join(BACKUP_DIR, f"priztiers_slot_{slot_id}.db")
            with open(file_path, "wb") as bf:
                bf.write(db_bytes)

            now_str = str(datetime.now(timezone.utc))
            cursor.execute("""
                INSERT OR REPLACE INTO manual_backups (slot_id, backup_name, file_path, timestamp)
                VALUES (?, ?, ?, ?)
            """, (slot_id, f"Save Slot #{slot_id}", file_path, now_str))
            conn.commit()

        file_obj = disnake.File(fp=io.BytesIO(db_bytes), filename=f"priztiers_save_{slot_id}.db")
        await inter.edit_original_response(
            content=(
                f"✅ **Сохранение успешно создано в слоте #{slot_id} из 20!**\n"
                f"Чтобы откатить базу к этому моменту, используйте `/save slot:{slot_id}`. Файл сохранения прикреплен:"
            ),
            file=file_obj
        )
    except Exception as e:
        logger.error(f"Error in /save: {e}")
        await inter.edit_original_response(content=f"❌ Ошибка при работе с `/save`: {e}")

@bot.slash_command(name="savealltime", description="Создать вечный файл со всеми сообщениями и каналами сервера (Только для Владельца сети)", default_member_permissions=disnake.Permissions(administrator=True))
async def savealltime_cmd(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    await inter.response.defer(ephemeral=True)
    try:
        guild = inter.guild
        snapshot_time = str(datetime.now(timezone.utc))
        sync_all_guilds_channels_state()

        channels_saved = 0
        with get_db_connection(ETERNAL_DB_FILE) as econn:
            for ch in guild.channels:
                cat_name = ch.category.name if getattr(ch, "category", None) else ""
                topic = getattr(ch, "topic", "") or ""
                pos = getattr(ch, "position", 0)
                ow_json = serialize_channel_overwrites(ch)
                econn.execute("""
                    INSERT INTO eternal_channels_archive
                    (guild_id, guild_name, channel_id, category_name, name, channel_type, topic, position, overwrites_json, snapshot_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(guild.id), guild.name, str(ch.id), cat_name, ch.name, str(ch.type), topic, pos, ow_json, snapshot_time))
                channels_saved += 1

            ecursor = econn.cursor()
            ecursor.execute("SELECT COUNT(*) FROM eternal_messages WHERE guild_id = ?", (str(guild.id),))
            msgs_count = ecursor.fetchone()[0]

            econn.execute("""
                INSERT INTO eternal_snapshots_meta (created_by, guild_id, guild_name, channels_count, messages_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(inter.author), str(guild.id), guild.name, channels_saved, msgs_count, snapshot_time))
            econn.commit()

        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        with open(ETERNAL_DB_FILE, "rb") as f:
            eternal_bytes = f.read()

        file_obj = disnake.File(fp=io.BytesIO(eternal_bytes), filename=f"priztiers_alltime_{timestamp_str}.db")
        await inter.edit_original_response(
            content=(
                f"✅ **Вечный файл сохранения (`/savealltime`) успешно создан!**\n"
                f"• Зафиксировано каналов: **{channels_saved}**\n"
                f"• Сообщений в вечном архиве: **{msgs_count}**\n"
                f"Для просмотра и восстановления используйте `/savealltimelook`. Файл прикреплен:"
            ),
            file=file_obj
        )
    except Exception as e:
        logger.error(f"Error in /savealltime: {e}")
        await inter.edit_original_response(content=f"❌ Ошибка создания вечного сохранения: {e}")

@bot.slash_command(name="savealltimelook", description="Просмотр всех сохранений и восстановление каналов (Только для Владельца сети)", default_member_permissions=disnake.Permissions(administrator=True))
async def savealltimelook_cmd(
    inter: disnake.ApplicationCommandInteraction,
    snapshot_id: int = commands.Param(default=None, description="ID вечного снимка для восстановления каналов (оставьте пустым для списка)")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    await inter.response.defer(ephemeral=True)
    try:
        with get_db_connection(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT slot_id, backup_name, timestamp FROM manual_backups ORDER BY slot_id ASC")
            slots = cursor.fetchall()

        with get_db_connection(ETERNAL_DB_FILE) as econn:
            ecursor = econn.cursor()
            ecursor.execute("""
                SELECT id, guild_name, channels_count, messages_count, created_at
                FROM eternal_snapshots_meta
                WHERE guild_id = ?
                ORDER BY id DESC LIMIT 10
            """, (str(inter.guild.id),))
            snaps = ecursor.fetchall()

            ecursor.execute("SELECT COUNT(*) FROM eternal_messages WHERE guild_id = ?", (str(inter.guild.id),))
            total_msgs = ecursor.fetchone()[0]

        embed = disnake.Embed(
            title="🗄️ Архив всех сохранений PrizTiers (/save & /savealltime)",
            color=0xa855f7,
            timestamp=datetime.now(timezone.utc)
        )

        if slots:
            slots_text = "\n".join([f"• **Слот #{s[0]}** — `{s[2][:19]}` (вернуть: `/save slot:{s[0]}`)" for s in slots])
        else:
            slots_text = "Нет сохранений в слотах `/save`."
        embed.add_field(name="💾 Слоты быстрого сохранения (/save 1-20)", value=slots_text[:1024], inline=False)

        if snaps:
            snaps_text = "\n".join([
                f"• **ID #{sn[0]}** | Каналов: **{sn[2]}** | Сообщений: **{sn[3]}** | `{sn[4][:19]}`"
                for sn in snaps
            ])
        else:
            snaps_text = "Вечных снимков пока нет. Создайте первый через `/savealltime`."
        embed.add_field(name="♾️ Вечные снимки сервера (/savealltime)", value=snaps_text[:1024], inline=False)
        embed.add_field(name="📨 Всего сообщений в вечной базе", value=f"**{total_msgs}** сообщений записано с этого сервера.", inline=False)

        target_snap_id = snapshot_id or (snaps[0][0] if snaps else None)
        if target_snap_id:
            embed.set_footer(text=f"Выбран снимок ID #{target_snap_id}. Нажмите кнопку ниже, чтобы вернуть пропавшие каналы.")
            await inter.edit_original_response(embed=embed, view=RestoreChannelsView(str(inter.guild.id), target_snap_id))
        else:
            await inter.edit_original_response(embed=embed)
    except Exception as e:
        logger.error(f"Error in /savealltimelook: {e}")
        await inter.edit_original_response(content=f"❌ Ошибка при просмотре архива сохранений: {e}")

@bot.slash_command(name="updatedsk", description="Полный перезапуск и обновление бота, выгрузка исходного кода (Только для Владельца)", default_member_permissions=disnake.Permissions(administrator=True))
async def updatedsk(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    try:
        script_path = __file__
        file_to_send = disnake.File(script_path, filename=os.path.basename(script_path)) if os.path.exists(script_path) else None

        if file_to_send:
            await inter.edit_original_response(
                content="🚀 **Бот перезапускается и обновляется!** Процесс перезапуска инициализирован. Исходный код системы прикреплен:",
                file=file_to_send
            )
        else:
            await inter.edit_original_response(content="🚀 **Бот перезапускается и обновляется!** Процесс перезапуска инициализирован.")

        logger.info("🔄 Выполняется физический перезапуск бота через команду /updatedsk...")
        python = sys.executable
        os.execl(python, python, *sys.argv)
    except Exception as e:
        logger.error(f"Error in updatedsk command: {e}")
        await inter.edit_original_response(content=f"❌ Произошла ошибка при выполнении обновления: {e}")

@bot.slash_command(name="profile", description="Посмотреть свой визуальный профиль или профиль игрока")
async def profile(inter: disnake.ApplicationCommandInteraction, member: disnake.Member = None):
    await inter.response.defer(ephemeral=True)
    target = member or inter.author
    card_bytes = await generate_profile_card_async(target.id, target.display_name)
    file = disnake.File(fp=card_bytes, filename="profile.png")
    await inter.edit_original_response(file=file)

@bot.slash_command(name="set_profile", description="Обновить свой игровой ник, сервер или пинг")
async def set_profile(
    inter: disnake.ApplicationCommandInteraction,
    ign: str = commands.Param(description="Игровой ник (IGN)"),
    server_name: str = commands.Param(default="PriZriT", description="Основной сервер"),
    ping: str = commands.Param(default="45ms", description="Средний пинг")
):
    discord_id = str(inter.author.id)
    if is_player_registered(discord_id):
        current_ign, _, _ = db_get_player_info(discord_id)
        if current_ign.lower() != ign.strip().lower():
            return await inter.response.send_message(
                f"❌ Ваш никнейм **`{current_ign}`** уже закреплен за аккаунтом. Сменить ник можно только через кнопку **Rename** (раз в 15 дней).",
                ephemeral=True
            )
        final_ign = current_ign
    else:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT discord_id FROM players WHERE LOWER(ign) = LOWER(?) AND discord_id != ?", (ign.strip(), discord_id))
            if cursor.fetchone():
                return await inter.response.send_message(f"❌ Никнейм **`{ign.strip()}`** уже занят другим игроком!", ephemeral=True)
        final_ign = ign.strip()
        set_last_rename(discord_id)

    db_save_player_info(discord_id, final_ign, server_name, ping, username=inter.author.name, discord_tag=str(inter.author))
    try:
        if inter.author.id != inter.guild.owner_id:
            await inter.author.edit(nick=final_ign)
    except Exception:
        pass
    await update_all_guilds_nickname(inter.author.id, final_ign)
    await inter.response.send_message(f"✅ Данные профиля обновлены: Ник `{final_ign}`, Сервер `{server_name}`, Пинг `{ping}` на всех серверах.", ephemeral=True)

@bot.slash_command(name="category_admin", description="Выдать полные права администратора только в текущей категории", default_member_permissions=disnake.Permissions(administrator=True))
async def category_admin(
    inter: disnake.ApplicationCommandInteraction,
    member: disnake.Member = commands.Param(description="Участник, которому нужно дать права в этой категории")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit) and not inter.author.guild_permissions.administrator:
        return await inter.response.send_message("❌ Эта команда доступна только владельцу сети или администраторам сервера!", ephemeral=True)

    category = inter.channel.category
    if not category:
        return await inter.response.send_message("❌ Этот канал не находится ни в какой категории!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    try:
        await category.set_permissions(
            member,
            read_messages=True,
            send_messages=True,
            manage_channels=True,
            manage_permissions=True,
            manage_messages=True,
            administrator=True
        )
        await inter.edit_original_response(content=f"✅ Участнику {member.mention} успешно выданы **полные права администратора** в категории `{category.name}`!")
    except Exception as e:
        await inter.edit_original_response(content=f"❌ Ошибка при выдаче прав на категорию: {e}")

@bot.slash_command(name="safe_admin", description="Выдать расширенные управляющие права на всех каналах без глобальной галочки Администратора", default_member_permissions=disnake.Permissions(administrator=True))
async def safe_admin(
    inter: disnake.ApplicationCommandInteraction,
    member: disnake.Member = commands.Param(description="Администратор, которому настраиваются безопасные права")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    try:
        overwrites = disnake.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            manage_channels=True,
            manage_permissions=True,
            manage_messages=True,
            manage_webhooks=True,
            mention_everyone=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            add_reactions=True,
            use_external_emojis=True,
            connect=True,
            speak=True,
            mute_members=True,
            deafen_members=True,
            move_members=True,
            administrator=False
        )

        for category in inter.guild.categories:
            await category.set_permissions(member, overwrite=overwrites)
        for channel in inter.guild.channels:
            if channel.category is None:
                await channel.set_permissions(member, overwrite=overwrites)

        await inter.edit_original_response(content=f"✅ Участнику {member.mention} успешно выданы все управляющие права по всем каналам и категориям **без галочки Администратора**!")
    except Exception as e:
        await inter.edit_original_response(content=f"❌ Ошибка при настройке безопасных прав: {e}")

@bot.slash_command(name="copy_category", description="Скопировать целую категорию со всеми каналами в другой Discord-сервер", default_member_permissions=disnake.Permissions(administrator=True))
async def copy_category(
    inter: disnake.ApplicationCommandInteraction,
    category_id: str = commands.Param(description="ID категории которую нужно скопировать"),
    target_guild_id: str = commands.Param(description="ID сервера, куда нужно вставить категорию")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    try:
        source_category = bot.get_channel(int(category_id))
        target_guild = bot.get_guild(int(target_guild_id))

        if not source_category or not isinstance(source_category, disnake.CategoryChannel):
            return await inter.edit_original_response(content="❌ Исходная категория не найдена или это не категория!")
        if not target_guild:
            return await inter.edit_original_response(content="❌ Целевой сервер не найден ботом!")

        new_category = await target_guild.create_category(
            name=source_category.name,
            position=source_category.position
        )

        for channel in source_category.channels:
            if isinstance(channel, disnake.TextChannel):
                await target_guild.create_text_channel(
                    name=channel.name,
                    category=new_category,
                    topic=channel.topic,
                    slowmode_delay=channel.slowmode_delay,
                    nsfw=channel.nsfw,
                    position=channel.position
                )
            elif isinstance(channel, disnake.VoiceChannel):
                await target_guild.create_voice_channel(
                    name=channel.name,
                    category=new_category,
                    bitrate=channel.bitrate,
                    user_limit=channel.user_limit,
                    position=channel.position
                )
            elif isinstance(channel, disnake.StageChannel):
                await target_guild.create_stage_channel(
                    name=channel.name,
                    category=new_category,
                    position=channel.position
                )

        await inter.edit_original_response(content=f"✅ Категория `{source_category.name}` и её каналы успешно скопированы на сервер **{target_guild.name}**!")
    except Exception as e:
        await inter.edit_original_response(content=f"❌ Ошибка при копировании категории: {e}")

@bot.slash_command(name="copy_channel", description="Скопировать один конкретный канал в другой Discord-сервер", default_member_permissions=disnake.Permissions(administrator=True))
async def copy_channel(
    inter: disnake.ApplicationCommandInteraction,
    channel_id: str = commands.Param(description="ID канала для копирования"),
    target_guild_id: str = commands.Param(description="ID сервера, куда вставить канал")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    try:
        source_channel = bot.get_channel(int(channel_id))
        target_guild = bot.get_guild(int(target_guild_id))

        if not source_channel:
            return await inter.edit_original_response(content="❌ Исходный канал не найден!")
        if not target_guild:
            return await inter.edit_original_response(content="❌ Целевой сервер не найден ботом!")

        if isinstance(source_channel, disnake.TextChannel):
            await target_guild.create_text_channel(
                name=source_channel.name,
                topic=source_channel.topic,
                slowmode_delay=source_channel.slowmode_delay,
                nsfw=source_channel.nsfw
            )
        elif isinstance(source_channel, disnake.VoiceChannel):
            await target_guild.create_voice_channel(
                name=source_channel.name,
                bitrate=source_channel.bitrate,
                user_limit=source_channel.user_limit
            )
        else:
            return await inter.edit_original_response(content="❌ Поддерживаются только текстовые и голосовые каналы для штучного копирования.")

        await inter.edit_original_response(content=f"✅ Канал `{source_channel.name}` успешно скопирован на сервер **{target_guild.name}**!")
    except Exception as e:
        await inter.edit_original_response(content=f"❌ Ошибка при копировании канала: {e}")

@bot.slash_command(name="setup_ping_panel", description="Отправить панель управления ролью уведомлений (пинг)", default_member_permissions=disnake.Permissions(manage_guild=True))
async def setup_ping_panel(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_admin_or_higher(inter.author, kit):
        return await inter.response.send_message("❌ Команда доступна только администраторам!", ephemeral=True)

    embed = disnake.Embed(
        title="🔔 Уведомления об очереди",
        description=(
            "Получайте уведомления когда очередь открывается или закрывается.\n\n"
            "Нажмите кнопку ниже, чтобы управлять ролью уведомлений."
        ),
        color=0xa855f7
    )
    embed.set_footer(text="Priz Tiers • Система уведомлений")

    await inter.channel.send(embed=embed, view=PingRolePanelView(kit))
    await inter.response.send_message("✅ Панель управления ролью уведомлений успешно отправлена!", ephemeral=True)

@bot.slash_command(name="setup_roles_panel", description="Отправить панель выбора ролей (Новости, Опросы, Матчмейкинг)", default_member_permissions=disnake.Permissions(manage_guild=True))
async def setup_roles_panel(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_admin_or_higher(inter.author, kit):
        return await inter.response.send_message("❌ Команда доступна только администраторам!", ephemeral=True)

    news_role_id = get_role_id(kit, 'news')
    polls_role_id = get_role_id(kit, 'polls')

    embed = disnake.Embed(
        title=f"📌 Получение ролей уведомлений — Кит: {kit}",
        description=(
            "**Нажми на эмодзи (кнопку ниже) что б получить роль для пинга!**\n\n"
            "• 🔊 **Новости** — получать важные объявления и новости проекта.\n"
            "• 🔔 **Опросы** — участвовать в опросах и голосованиях.\n"
            "• ⚔️ **Матчмейкинг** — находить матчи и соперников.\n\n"
            "**Связанные роли:**\n"
            f"• 🔊 Объявления: <@&{news_role_id}>\n"
            f"• 🔔 Опросы: <@&{polls_role_id}>"
        ),
        color=0xa855f7
    )
    embed.set_footer(text="Priz Tiers • Система ролей")

    await inter.channel.send(embed=embed, view=RolesSelectionView(kit))
    await inter.response.send_message("✅ Панель выбора ролей успешно отправлена!", ephemeral=True)

@bot.slash_command(name="tier", description="Выдать обычный ранг Priz List", default_member_permissions=disnake.Permissions(manage_messages=True))
async def tier_cmd(
    inter: disnake.ApplicationCommandInteraction,
    member: disnake.Member = commands.Param(description="Участник"),
    tier: str = param_tier_low,
    score: str = commands.Param(default="3-0", description="Счет матча (например: 3-0, 3-1, 3-2)")
):
    if not await check_tester_or_higher(inter):
        return

    await inter.response.defer(ephemeral=True)
    kit = db_get_server_kit(inter.guild.id)
    if not kit:
        return await inter.edit_original_response(content="❌ Сервер не привязан к киту через `/kit`!")

    tier_u = tier.upper()
    old_tiers = db_get_player_tiers(member.id)
    old_tier = old_tiers.get(kit, "None")

    db_save_tier(member.id, kit, tier_u, update_cooldown=True)
    db_increment_tester_test(inter.author.id, kit)

    ign, _, _ = db_get_player_info(member.id)
    if ign == "Unknown":
        ign = member.display_name
        db_save_player_info(member.id, ign, "Не указан", "Не указан")

    tester_ign, _, _ = db_get_player_info(inter.author.id)
    if tester_ign == "Unknown":
        tester_ign = inter.author.display_name

    db_log_match(member.id, ign, kit, old_tier, tier_u, score, inter.author.id, tester_ign)

    kit_roles = get_all_tier_role_ids(kit)
    role_id = kit_roles.get(tier_u)
    if role_id:
        role = inter.guild.get_role(role_id)
        if role:
            try:
                for r_id in kit_roles.values():
                    old_r = inter.guild.get_role(r_id)
                    if old_r and old_r in member.roles:
                        await member.remove_roles(old_r)
                await member.add_roles(role)
            except Exception as e:
                logger.warning(f"Error managing member tier roles: {e}")

    theme = get_kit_theme(kit)
    card_bytes = await generate_result_card_async(ign, tier_u, kit, tester_ign, score)
    file = disnake.File(fp=card_bytes, filename="result.png")

    embed = disnake.Embed(
        title=f"🏆 Ранг выдан | {kit}",
        description=f"**Игрок:** {member.mention} (`{ign}`)\n**Ранг:** `{tier_u}`\n**Счет:** `{score}`\n**Тестер:** {inter.author.mention} (`{tester_ign}`)",
        color=theme["hex"]
    )
    embed.set_image(url="attachment://result.png")

    target_ch_id = get_result_channel_id(kit)
    dest_channel = inter.guild.get_channel(target_ch_id) if target_ch_id else inter.channel
    if not dest_channel:
        dest_channel = inter.channel

    await dest_channel.send(embed=embed, file=file)
    await inter.edit_original_response(content="✅ Карточка создана и отправлена в канал результатов!")

@bot.slash_command(name="hightier", description="Выдать высокий ранг", default_member_permissions=disnake.Permissions(manage_messages=True))
async def hightier_cmd(
    inter: disnake.ApplicationCommandInteraction,
    member: disnake.Member = commands.Param(description="Участник"),
    tier: str = param_tier_high,
    score: str = commands.Param(default="3-0", description="Счет матча (например: 3-0, 3-1, 3-2)")
):
    if not await check_tester_or_higher(inter):
        return

    kit = db_get_server_kit(inter.guild.id)
    if not kit:
        return await inter.response.send_message("❌ Сервер не привязан к киту через `/kit`!", ephemeral=True)

    tier_u = tier.upper()

    if not is_network_owner(inter.author, kit):
        if tier_u in ["HT1", "RHT1", "LT1", "RLT1", "HT2", "RHT2"] and not is_head_tester_only(inter.author, kit):
            return await inter.response.send_message("❌ Топовые тиры (HT2-HT1) может выдавать исключительно Главный тестер!", ephemeral=True)
        if tier_u in ["LT2", "RLT2", "HT3", "RHT2", "HT2"] and not is_senior_or_head_tester(inter.author, kit):
            return await inter.response.send_message("❌ Средние высокие тиры (LT2-HT3) могут выдавать только Старшие и Главные тестеры!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    old_tiers = db_get_player_tiers(member.id)
    old_tier = old_tiers.get(kit, "None")

    db_save_tier(member.id, kit, tier_u, update_cooldown=True)
    db_increment_tester_test(inter.author.id, kit)

    ign, _, _ = db_get_player_info(member.id)
    if ign == "Unknown":
        ign = member.display_name
        db_save_player_info(member.id, ign, "Не указан", "Не указан")

    tester_ign, _, _ = db_get_player_info(inter.author.id)
    if tester_ign == "Unknown":
        tester_ign = inter.author.display_name

    db_log_match(member.id, ign, kit, old_tier, tier_u, score, inter.author.id, tester_ign)

    kit_roles = get_all_tier_role_ids(kit)
    role_id = kit_roles.get(tier_u)
    if role_id:
        role = inter.guild.get_role(role_id)
        if role:
            try:
                for r_id in kit_roles.values():
                    old_r = inter.guild.get_role(r_id)
                    if old_r and old_r in member.roles:
                        await member.remove_roles(old_r)
                await member.add_roles(role)
            except Exception as e:
                logger.warning(f"Error managing high tier roles: {e}")

    theme = get_kit_theme(kit)
    card_bytes = await generate_result_card_async(ign, tier_u, kit, tester_ign, score)
    file = disnake.File(fp=card_bytes, filename="result.png")

    embed = disnake.Embed(
        title=f"🔥 Высокий ранг выдан | {kit}",
        description=f"**Игрок:** {member.mention} (`{ign}`)\n**Ранг:** `{tier_u}`\n**Счет:** `{score}`\n**Тестер:** {inter.author.mention} (`{tester_ign}`)",
        color=theme["hex"]
    )
    embed.set_image(url="attachment://result.png")

    target_ch_id = get_result_channel_id(kit)
    dest_channel = inter.guild.get_channel(target_ch_id) if target_ch_id else inter.channel
    if not dest_channel:
        dest_channel = inter.channel

    await dest_channel.send(embed=embed, file=file)
    await inter.edit_original_response(content="✅ Карточка создана и отправлена в канал результатов!")

@bot.slash_command(name="punish", description="Выдать наказание игроку и заблокировать роль Restricted на время", default_member_permissions=disnake.Permissions(manage_messages=True))
async def punish(
    inter: disnake.ApplicationCommandInteraction,
    member: disnake.Member = commands.Param(description="Игрок"),
    reason: str = commands.Param(description="Причина"),
    duration: str = commands.Param(description="Срок (например: 5d, 1h, 30m, 10s)")
):
    if not await check_admin_or_higher(inter):
        return

    await inter.response.defer(ephemeral=True)

    kit = db_get_server_kit(inter.guild.id) or "Beast"
    restricted_role_id = get_role_id(kit, "restricted")

    if restricted_role_id:
        role = inter.guild.get_role(restricted_role_id)
        if role and role not in member.roles:
            try:
                await member.add_roles(role)
                seconds = parse_duration(duration)

                async def remove_restricted_role():
                    await asyncio.sleep(seconds)
                    try:
                        fresh_member = inter.guild.get_member(member.id) or await inter.guild.fetch_member(member.id)
                        if fresh_member and role in fresh_member.roles:
                            await fresh_member.remove_roles(role)
                    except Exception as e:
                        logger.warning(f"Error removing restricted role: {e}")

                bot.loop.create_task(remove_restricted_role())
            except Exception as e:
                logger.warning(f"Failed to add restricted role: {e}")

    theme = get_kit_theme(kit)
    embed = disnake.Embed(
        title="🔨 Наказание выдано",
        color=theme["hex"],
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Игрок", value=f"{member.mention}", inline=False)
    embed.add_field(name="Причина", value=reason, inline=False)
    embed.add_field(name="Срок", value=duration, inline=False)
    embed.add_field(name="Выдал", value=f"{inter.author.mention}", inline=False)

    await inter.channel.send(embed=embed)
    await inter.edit_original_response(content=f"✅ Наказание для {member.mention} успешно выдано на {duration}!")

@bot.slash_command(name="staff_log", description="Залогировать повышение или снятие роли у стаффа/тестера", default_member_permissions=disnake.Permissions(manage_guild=True))
async def staff_log(
    inter: disnake.ApplicationCommandInteraction,
    action: str = commands.Param(choices=["Повышен", "Снят"]),
    member: disnake.Member = commands.Param(description="Участник стаффа/тестер"),
    role_name: str = commands.Param(description="Название роли"),
    reason: str = commands.Param(default="Не указана", description="Причина (для снятия)")
):
    if not await check_admin_or_higher(inter):
        return

    ign, _, _ = db_get_player_info(member.id)
    if ign == "Unknown":
        ign = member.display_name

    color = 0x2ecc71 if action == "Повышен" else 0xe74c3c
    embed = disnake.Embed(color=color, timestamp=datetime.now(timezone.utc))

    if action == "Повышен":
        embed.title = f"📈 {ign} повышен!"
        embed.description = f"**Повышен до:** `{role_name}`"
    else:
        embed.title = f"📉 {ign} снят!"
        embed.description = f"**Снят с роли:** `{role_name}`\n**Причина:** `{reason}`"

    embed.add_field(name="Участник", value=f"{member.mention} (`{ign}`)", inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Модератор: {inter.author.display_name}")

    await inter.channel.send(embed=embed)
    await inter.response.send_message("✅ Действие со стаффом успешно залогировано!", ephemeral=True)

@bot.slash_command(name="tester_month", description="Объявить топ-10 лучших тестеров месяца", default_member_permissions=disnake.Permissions(manage_guild=True))
async def tester_month(inter: disnake.ApplicationCommandInteraction, tester_name: str, tests_count: int, month_name: str):
    if not await check_admin_or_higher(inter):
        return

    kit = db_get_server_kit(inter.guild.id) or "Beast"
    theme = get_kit_theme(kit)

    embed = disnake.Embed(
        title=f"🏆 Тестер Месяца — {month_name} — {kit}",
        description=(
            "Пришло время подвести итоги и объявить лучшего тестера прошедшего месяца!\n\n"
            f"**Победителем становится — {tester_name}**!\n"
            "Его продуктивность, активность и огромный вклад заслуживают отдельного уважения.\n\n"
            "**Награда за активную работу:**\n"
            "• Премиум-кастомизация профиля (1 месяц): доступ к смене цвета ника, кастомному фону и стилю.\n\n"
            "От лица высшей администрации выражаем огромную благодарность всем тестерам, которые усердно работали весь прошлый месяц!"
        ),
        color=theme["hex"],
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Тестов за месяц", value=str(tests_count), inline=True)
    embed.add_field(name="Период", value=f"{month_name} 2026", inline=True)
    embed.set_footer(text="Priz Tiers • Система наград тестеров")

    await inter.channel.send(content="", embed=embed)
    await inter.response.send_message("✅ Итоги месяца успешно опубликованы!", ephemeral=True)

@bot.slash_command(name="set_result_channel", description="Привязать текущий канал для отправки результатов тестов (Только для владельца сети)", default_member_permissions=disnake.Permissions(administrator=True))
async def set_result_channel(
    inter: disnake.ApplicationCommandInteraction,
    kit: str = commands.Param(choices=KITS, description="Выбрать кит")
):
    kit_check = db_get_server_kit(inter.guild.id) or kit
    if not is_network_owner(inter.author, kit_check):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    set_result_channel_db(kit, inter.channel.id)
    await inter.response.send_message(f"✅ Успешно! Канал {inter.channel.mention} назначен каналом для результатов по киту **{kit}**.", ephemeral=True)

@bot.slash_command(name="set_role_id", description="Обновить ID роли для конкретного кита (Только для владельца сети)", default_member_permissions=disnake.Permissions(administrator=True))
async def set_role_id(
    inter: disnake.ApplicationCommandInteraction,
    kit: str = commands.Param(choices=KITS, description="Выбрать кит"),
    role_key: str = commands.Param(
        choices=[
            "tester", "senior_tester", "head_tester", "helper", "moderator",
            "senior_moderator", "tier_manager", "senior_tier_manager",
            "curator", "project_head", "network_manager", "tier_admin", "admin", "network_owner",
            "whitelist", "member", "restricted", "news", "polls", "ping", "matchmaking",
            "LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "RLT2", "LT2", "RHT2", "HT2", "RLT1", "LT1", "RHT1", "HT1"
        ],
        description="Ключ роли в системе"
    ),
    role_id: str = commands.Param(description="Новый ID роли (цифры)")
):
    kit_check = db_get_server_kit(inter.guild.id) or kit
    if not is_network_owner(inter.author, kit_check):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    try:
        r_id_int = int(role_id.strip())
    except ValueError:
        return await inter.response.send_message("❌ ID роли должен состоять только из цифр!", ephemeral=True)

    set_role_id_db(kit, role_key, r_id_int)
    await inter.response.send_message(f"✅ Успешно обновлен ID для роли `{role_key}` в ките `{kit}` на `{r_id_int}`!", ephemeral=True)

@bot.slash_command(name="kit", description="Привязать весь Discord-сервер к конкретному киту", default_member_permissions=disnake.Permissions(administrator=True))
async def kit_command(inter: disnake.ApplicationCommandInteraction, kit: str = commands.Param(choices=KITS)):
    kit_check = db_get_server_kit(inter.guild.id) or kit
    if not is_network_owner(inter.author, kit_check) and not inter.author.guild_permissions.administrator:
        return await inter.response.send_message("❌ Недостаточно прав для привязки кита!", ephemeral=True)
    db_set_server_kit(inter.guild.id, kit)
    await inter.response.send_message(f"🌐 **Весь Discord-сервер** успешно привязан к киту: **{kit}**!", ephemeral=True)

@bot.slash_command(name="setup_test_panel", description="Отправить панель для прохождения теста", default_member_permissions=disnake.Permissions(manage_guild=True))
async def setup_test_panel(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id)
    if not kit:
        return await inter.response.send_message("❌ Сначала привяжите сервер к киту через `/kit`!", ephemeral=True)
    if not is_tester_or_admin(inter.author, kit):
        return await inter.response.send_message("❌ Эта панель доступна только тестерам и администраторам!", ephemeral=True)

    embed = disnake.Embed(
        title=f"🏆 Пройти тестирование — Кит: {kit}",
        description=(
            f"**Для регистрации и прохождения теста по киту {kit} нажмите на кнопку ниже.**\n\n"
            "• **1 аккаунт = 1 никнейм**\n"
            "• **Rename** — смена никнейма (КД 15 дней)\n"
            "⏳ **КД на тесты — 14 дней**"
        ),
        color=0x2b2d31
    )
    await inter.channel.send(embed=embed, view=TestPanelView(kit))
    await inter.response.send_message("✅ Панель отправлена!", ephemeral=True)

@bot.slash_command(name="setup_hightest_panel", description="Отправить панель высокого теста (Только для владельца сети)", default_member_permissions=disnake.Permissions(administrator=True))
async def setup_hightest_panel(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id)
    if not kit:
        return await inter.response.send_message("❌ Сначала привяжите сервер к киту через `/kit`!", ephemeral=True)
    if not is_network_owner(inter.author, kit):
        return await inter.response.send_message("❌ Эту команду может использовать исключительно Владелец сети!", ephemeral=True)

    embed = disnake.Embed(
        title=f"🔥 Высокие тесты — Кит: {kit}",
        description=(
            f"**Канал для прохождения высоких тестов по киту {kit}.**\n\n"
            "• Доступно игрокам с рангом **от LT3 и выше**.\n"
            "• Нажмите кнопку ниже, чтобы открыть тикет для прохождения высокого теста."
        ),
        color=0xa855f7
    )
    await inter.channel.send(embed=embed, view=HighTestPanelView(kit))
    await inter.response.send_message("✅ Панель высокого теста успешно отправлена!", ephemeral=True)

@bot.slash_command(name="setup_support_panel", description="Отправить панель поддержки", default_member_permissions=disnake.Permissions(manage_guild=True))
async def setup_support_panel(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_admin_or_higher(inter.author, kit):
        return await inter.response.send_message("❌ Только администраторы могут отправлять панель поддержки!", ephemeral=True)

    embed = disnake.Embed(
        title="🛠️ Центр Поддержки и Заявок Priz List",
        description=(
            "Выберите нужную категорию с помощью кнопок ниже:\n\n"
            "• 🚨 **Жалоба** — сообщить о нарушении или баге.\n"
            "• 🛠️ **Поддержка** — вопросы по работе сервера и боту.\n"
            "• 📋 **Заявка на тестера** — стать частью тир-тестеров.\n"
            "• ⚡ **Заявка в КП** — вступить в команду проекта."
        ),
        color=0x2b2d31
    )
    embed.set_footer(text="Priz List Support System")
    await inter.channel.send(embed=embed, view=SupportTicketView())
    await inter.response.send_message("✅ Панель поддержки успешно отправлена!", ephemeral=True)

@bot.slash_command(name="setup_queue_panel", description="Отправить живую очередь", default_member_permissions=disnake.Permissions(manage_guild=True))
async def setup_queue_panel(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id)
    if not kit:
        return await inter.response.send_message("❌ Сначала используйте `/kit`!", ephemeral=True)
    if not is_tester_or_admin(inter.author, kit):
        return await inter.response.send_message("❌ Только тестеры и администраторы могут настраивать очередь!", ephemeral=True)

    embed = disnake.Embed(title="🔴 Очередь закрыта", description="Очередь пуста.", color=0xe74c3c)
    embed.add_field(name="🛡️ Тиртестеры на смене", value="Нет активных тестеров", inline=False)
    embed.add_field(name="👥 В очереди (0)", value="---", inline=False)

    msg = await inter.channel.send(embed=embed, view=LiveQueueButtonsView(kit))
    queue_messages[kit] = msg
    save_queue_channel_db(kit, inter.channel.id, msg.id)
    await update_queue_embed(kit, inter.guild)
    await inter.response.send_message("✅ Панель живой очереди создана!", ephemeral=True)

@bot.slash_command(name="setup_tester_panel", description="Панель тестеров", default_member_permissions=disnake.Permissions(manage_guild=True))
async def setup_tester_panel(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id)
    if not kit:
        return await inter.response.send_message("❌ Сначала используйте `/kit`!", ephemeral=True)
    if not is_tester_or_admin(inter.author, kit):
        return await inter.response.send_message("❌ Только тестеры могут вызывать панель тестеров!", ephemeral=True)
    await inter.channel.send(embed=make_tester_embed(kit), view=TesterControlView(kit))
    await inter.response.send_message("✅ Панель тестеров отправлена!", ephemeral=True)

@bot.slash_command(name="leaderboard", description="Отправить таблицу лидеров игроков (автообновляемая)", default_member_permissions=disnake.Permissions(manage_guild=True))
async def leaderboard(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id)
    if not kit:
        return await inter.response.send_message("❌ Сервер не привязан к киту!", ephemeral=True)
    if not is_admin_or_higher(inter.author, kit):
        return await inter.response.send_message("❌ Доступно только администраторам!", ephemeral=True)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT discord_id, tier FROM user_tiers WHERE kit = ?", (kit,))
        rows = cursor.fetchall()

    user_scores = []
    for discord_id, tier in rows:
        pts = TIER_POINTS.get(tier, 0)
        ign, _, _ = db_get_player_info(discord_id)
        user_scores.append({"discord_id": discord_id, "ign": ign, "tier": tier, "points": pts})

    user_scores.sort(key=lambda x: x["points"], reverse=True)
    top_players = user_scores[:10]

    theme = get_kit_theme(kit)
    embed = disnake.Embed(title=f"👑 Таблица лидеров — Кит: {kit}", color=theme["hex"], timestamp=datetime.now(timezone.utc))
    if not top_players:
        embed.description = "Пока нет данных о рангах в этом ките."
    else:
        desc_lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for idx, p in enumerate(top_players):
            medal = medals[idx] if idx < len(medals) else f"`#{idx+1}`"
            desc_lines.append(f"{medal} **{p['ign']}** — Ранг: `{p['tier']}` | Очки: **{p['points']} PTS** (<@{p['discord_id']}>)")
        embed.description = "\n".join(desc_lines)

    embed.set_footer(text="Priz Tiers • Автоматическое обновление каждые 5 минут")
    msg = await inter.channel.send(embed=embed)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO active_leaderboards (guild_id, channel_id, message_id, lb_type) VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, lb_type) DO UPDATE SET channel_id = ?, message_id = ?
        """, (str(inter.guild.id), str(inter.channel.id), str(msg.id), "players", str(inter.channel.id), str(msg.id)))
        conn.commit()

    await inter.response.send_message("✅ Таблица лидеров успешно создана и добавлена в автообновление!", ephemeral=True)

@bot.slash_command(name="tester_leaderboard", description="Отправить таблицу лучших тестеров месяца (автообновляемая)", default_member_permissions=disnake.Permissions(manage_guild=True))
async def tester_leaderboard(inter: disnake.ApplicationCommandInteraction):
    kit = db_get_server_kit(inter.guild.id)
    if not kit:
        return await inter.response.send_message("❌ Сервер не привязан к киту!", ephemeral=True)
    if not is_admin_or_higher(inter.author, kit):
        return await inter.response.send_message("❌ Доступно только администраторам!", ephemeral=True)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT discord_id, test_count FROM tester_stats WHERE kit = ? ORDER BY test_count DESC LIMIT 10", (kit,))
        tester_rows = cursor.fetchall()

    theme = get_kit_theme(kit)
    embed = disnake.Embed(title=f"🏆 Лучшие тестеры месяца — Кит: {kit}", color=theme["hex"], timestamp=datetime.now(timezone.utc))
    if not tester_rows:
        embed.description = "В этом месяце тестеры еще не провели тестов."
    else:
        desc_lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for idx, (t_id, count) in enumerate(tester_rows):
            medal = medals[idx] if idx < len(medals) else f"`#{idx+1}`"
            member_obj = inter.guild.get_member(int(t_id))
            name = member_obj.display_name if member_obj else f"ID: {t_id}"
            desc_lines.append(f"{medal} **{name}** — Проведено тестов: **{count}** (<@{t_id}>)")
        embed.description = "\n".join(desc_lines)

    embed.set_footer(text="Priz Tiers • Автоматическое обновление каждые 5 минут")
    msg = await inter.channel.send(embed=embed)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO active_leaderboards (guild_id, channel_id, message_id, lb_type) VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, lb_type) DO UPDATE SET channel_id = ?, message_id = ?
        """, (str(inter.guild.id), str(inter.channel.id), str(msg.id), "testers", str(inter.channel.id), str(msg.id)))
        conn.commit()

    await inter.response.send_message("✅ Таблица тестеров успешно создана и добавлена в автообновление!", ephemeral=True)

@bot.slash_command(name="say", description="Отправить сообщение от имени бота", default_member_permissions=disnake.Permissions(manage_messages=True))
async def say(inter: disnake.ApplicationCommandInteraction, message: str):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_admin_or_higher(inter.author, kit):
        return await inter.response.send_message("❌ Доступно только администраторам!", ephemeral=True)

    if len(message) > 2000:
        await inter.response.defer(ephemeral=True)
        for i in range(0, len(message), 2000):
            chunk = message[i:i+2000]
            await inter.channel.send(chunk)
        await inter.edit_original_response(content="✅ Длинное сообщение было отправлено частями.")
    else:
        await inter.channel.send(message)
        await inter.response.send_message("Отправлено.", ephemeral=True)

@bot.slash_command(name="saywebhook", description="Отправить сообщение через вебхук от имени бота/проекта", default_member_permissions=disnake.Permissions(manage_messages=True))
async def saywebhook(
    inter: disnake.ApplicationCommandInteraction,
    message: str = commands.Param(description="Текст сообщения"),
    title: str = commands.Param(default=None, description="Заголовок для Embed (опционально)"),
    username: str = commands.Param(default=None, description="Кастомное имя отправителя (по умолчанию: имя бота)"),
    avatar_url: str = commands.Param(default=None, description="Ссылка на кастомный аватар (опционально)")
):
    kit = db_get_server_kit(inter.guild.id) or "Beast"
    if not is_admin_or_higher(inter.author, kit):
        return await inter.response.send_message("❌ Команда доступна только администраторам и руководству!", ephemeral=True)

    await inter.response.defer(ephemeral=True)

    try:
        webhooks = await inter.channel.webhooks()
        webhook = next((w for w in webhooks if w.user == bot.user), None)
        if not webhook:
            webhook = await inter.channel.create_webhook(name="PrizTiers Webhook")

        name_to_use = username or bot.user.display_name
        avatar_to_use = avatar_url or bot.user.display_avatar.url

        theme = get_kit_theme(kit)

        if title:
            embed = disnake.Embed(
                title=title,
                description=message,
                color=theme["hex"],
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"Опубликовано • {kit}")
            await webhook.send(
                embed=embed,
                username=name_to_use,
                avatar_url=avatar_to_use
            )
        else:
            await webhook.send(
                content=message,
                username=name_to_use,
                avatar_url=avatar_to_use
            )

        await inter.edit_original_response(content="✅ Сообщение через вебхук успешно отправлено!")
    except Exception as e:
        await inter.edit_original_response(content=f"❌ Ошибка при отправке сообщения через вебхук: {e}")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("❌ DISCORD_TOKEN не задан в .env или переменных окружения!")
        sys.exit(1)
    bot.run(DISCORD_TOKEN)
