#!/usr/bin/env python3
"""
process_member_prefs.py — Handle user watchlist and risk preference commands
from private trading channels.

Reads recent messages in each member's private channel looking for:
  watchlist: NVDA, AAPL, MSFT
  risk: conservative | moderate | aggressive

Updates logs/member_prefs.json with preferences.
"""
import sys, os, json, subprocess, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PREFS_FILE = REPO / "logs" / "member_prefs.json"
CHANNELS_FILE = REPO / "logs" / "trading_member_channels.json"

VALID_RISK = ["conservative", "moderate", "aggressive"]

def load_prefs():
    if PREFS_FILE.exists():
        try: return json.loads(PREFS_FILE.read_text())
        except: pass
    return {}

def save_prefs(prefs):
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREFS_FILE.write_text(json.dumps(prefs, indent=2))

def load_channels():
    if CHANNELS_FILE.exists():
        try: return json.loads(CHANNELS_FILE.read_text()).get("provisioned", [])
        except: pass
    return []

def get_bot_token():
    try:
        config = json.loads(Path('/Users/omarabdelmaksoud/.openclaw/openclaw.json').read_text())
        return config['channels']['discord']['token']
    except: return None

def fetch_recent_messages(channel_id, token, limit=10):
    """Fetch recent messages from a Discord channel."""
    try:
        r = requests.get(
            f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}",
            headers={"Authorization": f"Bot {token}"},
            timeout=5
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[{channel_id}] Error: {e}")
    return []

def parse_command(content):
    """Parse watchlist: or risk: commands from message content."""
    content_lower = content.lower().strip()

    if content_lower.startswith("watchlist:"):
        tickers_raw = content[len("watchlist:"):].strip()
        tickers = [t.strip().upper() for t in tickers_raw.replace(",", " ").split() if t.strip()]
        if tickers:
            return {"type": "watchlist", "value": tickers}

    elif content_lower.startswith("risk:"):
        risk_raw = content[len("risk:"):].strip().lower()
        for valid in VALID_RISK:
            if valid in risk_raw:
                return {"type": "risk", "value": valid}

    return None

def post_discord(channel_id, message):
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", channel_id, "--message", message],
            capture_output=True, timeout=15
        )
    except Exception as e:
        print(f"WARN: Discord post failed for {channel_id}: {e}")

def main():
    print(f"Member Prefs | {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    token = get_bot_token()
    if not token:
        print("ERROR: No bot token found")
        return

    channels = load_channels()
    prefs = load_prefs()
    updates = 0

    for member in channels:
        channel_id = str(member.get("channel_id", ""))
        user_id = str(member.get("user_id", ""))
        username = member.get("username", "?")

        if not channel_id:
            continue

        messages = fetch_recent_messages(channel_id, token, limit=5)

        for msg in messages:
            # Only process user messages (not bot messages)
            if msg.get("author", {}).get("bot"):
                continue

            content = msg.get("content", "")
            cmd = parse_command(content)
            if not cmd:
                continue

            # Update prefs
            if user_id not in prefs:
                prefs[user_id] = {
                    "username": username,
                    "channel_id": channel_id,
                    "watchlist": [],
                    "risk": "moderate",
                    "updated": datetime.now(timezone.utc).isoformat()
                }

            if cmd["type"] == "watchlist":
                old = prefs[user_id].get("watchlist", [])
                prefs[user_id]["watchlist"] = cmd["value"]
                prefs[user_id]["updated"] = datetime.now(timezone.utc).isoformat()
                print(f"[{username}] Watchlist updated: {cmd['value']}")

                if old != cmd["value"]:
                    post_discord(channel_id,
                        f"✅ Watchlist updated!\n"
                        f"Tracking: {', '.join(cmd['value'])}\n"
                        f"You'll get alerts when Cooper finds setups on these tickers. — Cooper 🦅"
                    )
                    updates += 1

            elif cmd["type"] == "risk":
                old = prefs[user_id].get("risk", "moderate")
                prefs[user_id]["risk"] = cmd["value"]
                prefs[user_id]["updated"] = datetime.now(timezone.utc).isoformat()
                print(f"[{username}] Risk updated: {cmd['value']}")

                if old != cmd["value"]:
                    descriptions = {
                        "conservative": "Small positions, tight stops. Safety first.",
                        "moderate": "Standard Kelly sizing, -3% stop, +8% target.",
                        "aggressive": "Full Kelly sizing, wider stops on high-conviction."
                    }
                    post_discord(channel_id,
                        f"✅ Risk profile set: **{cmd['value'].upper()}**\n"
                        f"{descriptions[cmd['value']]} — Cooper 🦅"
                    )
                    updates += 1

            break  # Only process the most recent command per channel

    save_prefs(prefs)
    print(f"Updates: {updates} | Members tracked: {len(prefs)}")

if __name__ == "__main__":
    main()
