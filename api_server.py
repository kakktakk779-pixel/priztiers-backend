import os
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

DB_PATH = BASE_DIR / "priztiers.db"
BACKUP_DIR = BASE_DIR / "backups_save"
LIVE_JSON_PATH = BASE_DIR / "site_state_live.json"
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

CLIENT_ID = (os.getenv("CLIENT_ID") or "").strip()
CLIENT_SECRET = (os.getenv("CLIENT_SECRET") or "").strip()

BACKUP_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
CORS(app)


def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def atomic_write_json(target_path: Path, payload: dict):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(target_path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp_path), str(target_path))


def write_backup_snapshot(state_payload: dict):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slot_file = BACKUP_DIR / f"site_state_{ts}.json"
    latest_backup = BACKUP_DIR / "site_state_latest.json"
    atomic_write_json(LIVE_JSON_PATH, state_payload)
    atomic_write_json(latest_backup, state_payload)
    atomic_write_json(slot_file, state_payload)

    backups = sorted(BACKUP_DIR.glob("site_state_2*.json"))
    for old_file in backups[:-30]:
        try:
            old_file.unlink()
        except OSError:
            pass


def normalize_state(raw: dict) -> dict:
    return {
        "players": raw.get("players") if isinstance(raw.get("players"), dict) else {},
        "views": raw.get("views") if isinstance(raw.get("views"), dict) else {},
        "bgs": raw.get("bgs") if isinstance(raw.get("bgs"), dict) else {},
        "skins": raw.get("skins") if isinstance(raw.get("skins"), dict) else {},
        "poses": raw.get("poses") if isinstance(raw.get("poses"), dict) else {},
        "history": raw.get("history") if isinstance(raw.get("history"), list) else [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_latest_state() -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT snapshot_data, timestamp FROM site_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row and row["snapshot_data"]:
            try:
                parsed = json.loads(row["snapshot_data"])
                state = normalize_state(parsed)
                state["updated_at"] = row["timestamp"] or state["updated_at"]
                return state
            except json.JSONDecodeError:
                pass

    if LIVE_JSON_PATH.exists():
        try:
            with open(LIVE_JSON_PATH, "r", encoding="utf-8") as f:
                return normalize_state(json.load(f))
        except Exception:
            pass

    return normalize_state({})


def persist_state(raw_state: dict) -> dict:
    state = normalize_state(raw_state)
    serialized = json.dumps(state, ensure_ascii=False)
    now_iso = state["updated_at"]

    with get_db() as conn:
        conn.execute(
            "INSERT INTO site_snapshots (snapshot_data, timestamp) VALUES (?, ?)",
            (serialized, now_iso),
        )

        for ign, pdata in state["players"].items():
            if not isinstance(pdata, dict):
                continue
            d_id = str(pdata.get("discord_id") or "").strip()
            if d_id:
                conn.execute(
                    """
                    INSERT INTO players (discord_id, username, ign, server_name, ping, discord_tag, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM players WHERE discord_id = ?), ?))
                    ON CONFLICT(discord_id) DO UPDATE SET
                        ign = excluded.ign,
                        server_name = COALESCE(excluded.server_name, players.server_name),
                        ping = COALESCE(excluded.ping, players.ping)
                    """,
                    (
                        d_id,
                        ign,
                        ign,
                        pdata.get("server") or "Не указан",
                        str(pdata.get("ping") or "Не указан"),
                        ign,
                        d_id,
                        now_iso,
                    ),
                )
                for kit_key, db_kit in [("beast", "Beast"), ("mace", "Mace"), ("carts", "Carts")]:
                    t_val = str(pdata.get(kit_key) or "").strip().upper()
                    if t_val and t_val not in ("0", "NONE", "NULL", "-"):
                        conn.execute(
                            """
                            INSERT INTO user_tiers (discord_id, kit, tier, last_tested)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(discord_id, kit) DO UPDATE SET
                                tier = excluded.tier,
                                last_tested = excluded.last_tested
                            """,
                            (d_id, db_kit, t_val, now_iso),
                        )
        conn.commit()

    write_backup_snapshot(state)
    return state


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "PrizTiers API", "db": str(DB_PATH)})


@app.route("/api/data/get", methods=["GET"])
def api_data_get():
    state = load_latest_state()
    return jsonify(state)


@app.route("/api/data/save", methods=["POST"])
def api_data_save():
    data = request.get_json(silent=True) or {}
    saved = persist_state(data)
    return jsonify({"success": True, "updated_at": saved["updated_at"], "state": saved})


@app.route("/api/user/set-nick", methods=["POST"])
def api_set_nick():
    body = request.get_json(silent=True) or {}
    discord_id = str(body.get("discord_id") or "").strip()
    nickname = str(body.get("nickname") or "").strip()

    if not nickname:
        return jsonify({"success": False, "error": "Никнейм не указан"}), 400

    state = load_latest_state()
    players = state["players"]

    for existing_ign, pdata in players.items():
        if existing_ign.lower() == nickname.lower():
            owner_id = str((pdata or {}).get("discord_id") or "").strip()
            if owner_id and discord_id and owner_id != discord_id:
                return jsonify({"success": False, "error": "Этот никнейм уже занят другим игроком!"}), 409

    if nickname not in players:
        players[nickname] = {
            "beast": "0",
            "mace": "0",
            "carts": "0",
            "title": "",
            "discord_id": discord_id,
        }
    elif discord_id:
        players[nickname]["discord_id"] = discord_id

    persist_state(state)
    return jsonify({"success": True, "nickname": nickname, "discord_id": discord_id})


@app.route("/api/auth/code", methods=["POST"])
def api_auth_code():
    body = request.get_json(silent=True) or {}
    code = str(body.get("code") or "").strip()
    if not code:
        return jsonify({"status": "error", "message": "Введите код"}), 400

    with get_db() as conn:
        row = conn.execute(
            "SELECT discord_id, created_at FROM login_codes WHERE code = ?",
            (code,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Неверный или просроченный код!"}), 404

        discord_id = str(row["discord_id"])
        player_row = conn.execute(
            "SELECT ign, username FROM players WHERE discord_id = ?",
            (discord_id,),
        ).fetchone()

    nickname = ""
    if player_row:
        nickname = player_row["ign"] or player_row["username"] or ""

    return jsonify({
        "status": "success",
        "discord_id": discord_id,
        "nickname": nickname,
        "created_at": row["created_at"],
    })


@app.route("/api/auth/discord", methods=["POST"])
def api_auth_discord():
    body = request.get_json(silent=True) or {}
    code = str(body.get("code") or "").strip()
    redirect_uri = str(body.get("redirect_uri") or "").strip()

    if not code:
        return jsonify({"error": "Не передан код авторизации"}), 400
    if not CLIENT_ID or not CLIENT_SECRET:
        return jsonify({"error": "Не заданы CLIENT_ID или CLIENT_SECRET в .env"}), 500

    token_res = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    token_data = token_res.json()
    access_token = token_data.get("access_token")
    if not token_res.ok or not access_token:
        return jsonify({"error": "Ошибка обмена кода Discord", "details": token_data}), 400

    user_res = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    user_data = user_res.json()
    discord_id = str(user_data.get("id") or "")
    if not user_res.ok or not discord_id:
        return jsonify({"error": "Не удалось получить профиль Discord", "details": user_data}), 400

    with get_db() as conn:
        player_row = conn.execute(
            "SELECT ign, username, created_at FROM players WHERE discord_id = ?",
            (discord_id,),
        ).fetchone()

    nickname = (player_row["ign"] or player_row["username"]) if player_row else ""
    created_at = player_row["created_at"] if player_row else ""

    return jsonify({
        "discord_id": discord_id,
        "username": user_data.get("username", ""),
        "nickname": nickname,
        "created_at": created_at,
    })


@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def serve_static(path):
    file_path = BASE_DIR / path
    if file_path.exists() and file_path.is_file():
        return send_from_directory(str(BASE_DIR), path)
    return send_from_directory(str(BASE_DIR), "index.html")


if __name__ == "__main__":
    print(f"[PrizTiers API] Запуск на http://0.0.0.0:{FLASK_PORT} | DB: {DB_PATH}")
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False)