import os
import json
import requests
import sqlite3
from datetime import datetime, timezone, timedelta
import telebot
from telebot import types

# ---------------------------
# Load configuration from config.json
# ---------------------------
with open("config.json", "r") as f:
    config = json.load(f)
# config example:
# {
#   "bot_token": "...",
#   "adminids": [123456789],
#   "groupid": -1001234567890,
#   "apikey": "...",
#   "tocheck": 10
# }

FIXED_MATCHES_FILE = "FixedMatches.json"
PREDICTIONS_DB_FILE = "predictions.db"
USERS_DIR = "users"

# Used to hold partial admin states (e.g., for broadcast flow)
ADMIN_STATES = {}

# To store fixture data from the external API while setting matches
CURRENT_FIXTURES = {}

# ---------------------------
# Helpers
# ---------------------------
def load_fixed_matches():
    if os.path.exists(FIXED_MATCHES_FILE):
        try:
            with open(FIXED_MATCHES_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_fixed_matches(data):
    with open(FIXED_MATCHES_FILE, "w") as f:
        json.dump(data, f, indent=4)

def is_fixture_set(fixture_id):
    fixed = load_fixed_matches()
    return any(str(match.get("fixture_id")) == str(fixture_id) for match in fixed)

def fetch_fixtures():
    """
    Fetch upcoming fixtures from external API for league=39, season=2024, status=NS,
    limited to the next 20 days.
    """
    url = "https://v3.football.api-sports.io/fixtures"
    params = {
        "league": 39,   # Premier League
        "season": 2024,
        "status": "NS"
    }
    headers = {
        "x-apisports-key": config["apikey"]
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        fixtures = data.get("response", [])
    except:
        fixtures = []

    now = datetime.now(timezone.utc)
    upcoming = []
    for fix in fixtures:
        date_str = fix["fixture"]["date"]
        try:
            fix_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except:
            continue
        if now <= fix_date <= now + timedelta(days=20):
            upcoming.append(fix)
    upcoming.sort(key=lambda f: datetime.fromisoformat(
        f["fixture"]["date"].replace("Z", "+00:00")
    ))
    return upcoming

def count_predictions_for_fixture(fixture_id):
    """
    Return how many predictions are stored for fixture_<fixture_id> in predictions.db
    Returns 0 if table doesn't exist or no entries.
    """
    table_name = f"fixture_{fixture_id}"
    conn = sqlite3.connect(PREDICTIONS_DB_FILE)
    c = conn.cursor()
    try:
        c.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        (cnt,) = c.fetchone()
    except:
        cnt = 0
    conn.close()
    return cnt

def get_total_users():
    """Count how many user .json files exist in users/."""
    if not os.path.exists(USERS_DIR):
        return 0
    files = os.listdir(USERS_DIR)
    # Only count .json
    return sum(1 for f in files if f.endswith(".json"))

# ---------------------------
# Admin Menu Displays
# ---------------------------
def show_admin_main_menu(bot, chat_id, message_id=None):
    """
    Show or update the main admin menu.
    """
    text = "👋 Hey Manager, what are you gonna cook today? 🍳"
    markup = types.InlineKeyboardMarkup()
    btn_set_match    = types.InlineKeyboardButton("⚽ Set Match", callback_data="set_match")
    btn_fixture      = types.InlineKeyboardButton("📋 Fixture", callback_data="fixture")
    btn_participants = types.InlineKeyboardButton("👥 Participants", callback_data="participants")
    btn_broadcast    = types.InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")
    btn_remove_match = types.InlineKeyboardButton("🗑️ Remove Match", callback_data="remove_match")
    markup.row(btn_set_match, btn_fixture)
    markup.row(btn_participants, btn_broadcast)
    markup.add(btn_remove_match)

    if message_id:
        # Try editing existing message
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                                  text=text, reply_markup=markup)
            return
        except:
            pass
    # Otherwise send new
    bot.send_message(chat_id, text, reply_markup=markup)

def show_match_selection(bot, call):
    """
    Show upcoming fixtures from external API with an option to set them.
    """
    global CURRENT_FIXTURES
    fixtures = fetch_fixtures()
    CURRENT_FIXTURES = {}
    markup = types.InlineKeyboardMarkup()

    for fix in fixtures:
        fixture_id = str(fix["fixture"]["id"])
        date_str = fix["fixture"]["date"]
        try:
            f_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except:
            continue
        date_txt = f_date.strftime("%d %b")
        home_team = fix["teams"]["home"]["name"]
        away_team = fix["teams"]["away"]["name"]
        btn_text = f"📅 {date_txt}: {home_team} vs {away_team}"
        if is_fixture_set(fixture_id):
            btn_text += " 🔴"
        CURRENT_FIXTURES[fixture_id] = fix
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"setmatch:{fixture_id}"))

    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_back"))
    text = "👉 Select a match to set:"
    try:
        bot.edit_message_text(chat_id=call.message.chat.id,
                              message_id=call.message.message_id,
                              text=text, reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=markup)
    # Safely answer the callback
    try:
        bot.answer_callback_query(call.id)
    except:
        pass

def show_remove_match_menu(bot, call):
    """
    List current fixed matches, let admin remove them, plus a Back button.
    """
    fixed_list = load_fixed_matches()
    markup = types.InlineKeyboardMarkup()
    if not fixed_list:
        text = "⚠️ No fixed matches to remove."
    else:
        text = "👉 Select a match to remove:"
        for m in fixed_list:
            f_id = str(m["fixture_id"])
            home = m["home"]["name"]
            away = m["away"]["name"]
            match_time = datetime.fromtimestamp(m["timestamp"] + 30, timezone.utc)
            date_txt = match_time.strftime("%d %b")
            btn_text = f"📅 {date_txt}: {home} vs {away}"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"removematch:{f_id}"))

    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_back"))
    try:
        bot.edit_message_text(chat_id=call.message.chat.id,
                              message_id=call.message.message_id,
                              text=text,
                              reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=markup)
    try:
        bot.answer_callback_query(call.id)
    except:
        pass

def show_fixtures_info(bot, call):
    """
    Displays current fixed matches sorted by timestamp, plus how many predictions each has.
    """
    fixed_list = load_fixed_matches()
    fixed_list.sort(key=lambda x: x.get("timestamp", 0))

    lines = []
    if not fixed_list:
        lines.append("No fixed matches yet.")
    else:
        lines.append("<b>Current Fixed Matches</b>\n")
        for fm in fixed_list:
            f_id = str(fm["fixture_id"])
            tstamp = fm["timestamp"] + 30
            date_str = datetime.fromtimestamp(tstamp, timezone.utc).strftime("%d %b %Y %H:%M")
            home = fm["home"]["name"]
            away = fm["away"]["name"]
            pred_count = count_predictions_for_fixture(f_id)
            lines.append(
                f"• <b>{home} vs {away}</b> on {date_str}\n"
                f"   FixtureID: {f_id}, Predictions: {pred_count}"
            )
    text = "\n".join(lines)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_back"))
    try:
        bot.edit_message_text(call.message.chat.id, call.message.message_id,
                              text, parse_mode="HTML", reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
    try:
        bot.answer_callback_query(call.id)
    except:
        pass

def show_participants_info(bot, call):
    """
    Displays the total number of participants (count of .json in users/).
    """
    total_users = get_total_users()
    text = f"👥 <b>Total Participants:</b> {total_users}\n\nYou can expand this to show more info."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_back"))
    try:
        bot.edit_message_text(call.message.chat.id, call.message.message_id,
                              text, parse_mode="HTML", reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
    try:
        bot.answer_callback_query(call.id)
    except:
        pass

# ---------------------------
# Broadcast Flow
# ---------------------------
def on_broadcast_callback(bot, call):
    """
    Initiate the broadcast flow by setting ADMIN_STATES[user_id] = 'broadcast_wait'.
    Then we prompt the admin for their message.
    """
    user_id = call.from_user.id
    ADMIN_STATES[user_id] = "broadcast_wait"
    text = "Please send the broadcast message you wish to send to ALL users."
    try:
        bot.edit_message_text(call.message.chat.id, call.message.message_id, text)
    except:
        bot.send_message(call.message.chat.id, text)
    try:
        bot.answer_callback_query(call.id)
    except:
        pass

def broadcast_to_all(bot, text):
    """
    Sends the given text to all user_id found in the users/ folder.
    Returns how many were sent.
    """
    if not os.path.exists(USERS_DIR):
        return 0
    files = [f for f in os.listdir(USERS_DIR) if f.endswith(".json")]
    count_sent = 0
    for filename in files:
        user_id_str = filename.replace(".json", "")
        try:
            user_id = int(user_id_str)
        except:
            continue
        try:
            bot.send_message(user_id, text, parse_mode="HTML")
            count_sent += 1
        except Exception as e:
            print(f"[broadcast WARNING] Could not send to {user_id}: {e}")
    return count_sent

# ---------------------------
# Match Setting Helpers
# ---------------------------
def handle_set_match_callback(bot, call):
    """
    Called when admin picks a fixture to set from the upcoming list.
    We add it to FixedMatches.json if not already present.
    """
    fixture_id = call.data.split(":", 1)[1]
    if is_fixture_set(fixture_id):
        try:
            bot.answer_callback_query(call.id, "⚠️ This match has been set already!", show_alert=True)
        except:
            pass
        return

    fix = CURRENT_FIXTURES.get(fixture_id)
    if not fix:
        try:
            bot.answer_callback_query(call.id, "❌ Fixture data not found.")
        except:
            pass
        return

    try:
        fixture_timestamp = fix["fixture"]["timestamp"]
        base_timestamp = fixture_timestamp - 30
        fm_list = load_fixed_matches()
        new_timestamp = base_timestamp
        existing_timestamps = {m["timestamp"] for m in fm_list}
        while new_timestamp in existing_timestamps:
            new_timestamp += 1

        match_entry = {
            "fixture_id": fixture_id,
            "home": {
                "id": fix["teams"]["home"]["id"],
                "name": fix["teams"]["home"]["name"]
            },
            "away": {
                "id": fix["teams"]["away"]["id"],
                "name": fix["teams"]["away"]["name"]
            },
            "timestamp": new_timestamp
        }
        fm_list.append(match_entry)
        save_fixed_matches(fm_list)
    except:
        try:
            bot.answer_callback_query(call.id, "❌ Error processing fixture data.")
        except:
            pass
        return

    # Confirm to admin
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("⚽ Set Another", callback_data="set_match"),
        types.InlineKeyboardButton("🏠 Main Menu", callback_data="admin_main")
    )
    text = "✅ Match set successfully!"
    try:
        bot.edit_message_text(call.message.chat.id, call.message.message_id,
                              text, reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=markup)
    try:
        bot.answer_callback_query(call.id)
    except:
        pass


# ---------------------------
# Register Admin Handlers
# ---------------------------
def register_admin_handlers(bot):
    @bot.message_handler(commands=["admin"])
    def admin_command_handler(message):
        # Only allow authorized admin users
        if str(message.from_user.id) not in map(str, config.get("adminids", [])):
            bot.reply_to(message, "🚫 You are not authorized to use this command.")
            return
        show_admin_main_menu(bot, message.chat.id)

    # Only handle callbacks that match admin commands,
    # so we don't block user callbacks from user_play or other modules.
    @bot.callback_query_handler(func=lambda call: _is_admin_callback(call.data))
    def admin_callback_router(call):
        # Check admin
        if str(call.from_user.id) not in map(str, config.get("adminids", [])):
            try:
                bot.answer_callback_query(call.id, "🚫 Unauthorized")
            except:
                pass
            return

        data = call.data
        if data == "set_match":
            show_match_selection(bot, call)
        elif data.startswith("setmatch:"):
            handle_set_match_callback(bot, call)
        elif data == "remove_match":
            show_remove_match_menu(bot, call)
        elif data.startswith("removematch:"):
            fixture_id = data.split(":", 1)[1]
            fm_list = load_fixed_matches()
            new_list = [m for m in fm_list if str(m["fixture_id"]) != fixture_id]
            if len(new_list) == len(fm_list):
                # Not found
                try:
                    bot.answer_callback_query(call.id, "⚠️ Match not found!")
                except:
                    pass
                return
            save_fixed_matches(new_list)
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("🗑️ Remove Another", callback_data="remove_match"),
                types.InlineKeyboardButton("🏠 Main Menu", callback_data="admin_main")
            )
            text = "🚮 Match removed successfully!"
            try:
                bot.edit_message_text(call.message.chat.id, call.message.message_id,
                                      text, reply_markup=markup)
            except:
                bot.send_message(call.message.chat.id, text, reply_markup=markup)
            try:
                bot.answer_callback_query(call.id)
            except:
                pass
        elif data == "fixture":
            show_fixtures_info(bot, call)
        elif data == "participants":
            show_participants_info(bot, call)
        elif data == "broadcast":
            on_broadcast_callback(bot, call)
        elif data == "admin_main":
            show_admin_main_menu(bot, call.message.chat.id, call.message.message_id)
            try:
                bot.answer_callback_query(call.id)
            except:
                pass
        elif data == "admin_back":
            show_admin_main_menu(bot, call.message.chat.id, call.message.message_id)
            try:
                bot.answer_callback_query(call.id)
            except:
                pass
        else:
            try:
                bot.answer_callback_query(call.id, "Unrecognized admin action.")
            except:
                pass

    # Handle the broadcast flow
    @bot.message_handler(func=lambda msg: _is_admin_in_broadcast_state(msg))
    def handle_broadcast_message(message):
        user_id = message.from_user.id
        broadcast_text = message.text
        # Clear the admin state
        ADMIN_STATES[user_id] = None
        count_sent = broadcast_to_all(bot, broadcast_text)
        ack = f"✅ Broadcast delivered to {count_sent} user(s)."
        bot.reply_to(message, ack)
        # Return to admin menu
        show_admin_main_menu(bot, message.chat.id)

# ---------------------------
# Utility
# ---------------------------
def _is_admin_in_broadcast_state(msg):
    if not msg or not msg.from_user:
        return False
    uid = msg.from_user.id
    # Must be in admin list AND in broadcast_wait state
    if str(uid) not in map(str, config.get("adminids", [])):
        return False
    return ADMIN_STATES.get(uid) == "broadcast_wait"

def _is_admin_callback(data):
    """
    Returns True if the callback data is recognized as an admin action,
    meaning we should route it in admin_callback_router.
    Otherwise, user or other modules can handle it.
    """
    # Here are the known admin data prefixes/values
    admin_keys = [
        "set_match", "remove_match", "admin_main", "admin_back",
        "fixture", "participants", "broadcast"
    ]
    # Also anything that starts with setmatch: or removematch:
    if data in admin_keys:
        return True
    if data.startswith("setmatch:"):
        return True
    if data.startswith("removematch:"):
        return True
    return False
