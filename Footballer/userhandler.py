import os
import json
import sqlite3
import telebot
from telebot import types

# Import our new extras file
from user_extras import register_user_extra_handlers

# Path to the SQLite database file.
DB_FILE = "predictions.db"
# Folder for storing user JSON files.
USERS_DIR = "users"

# -----------------------------------------------------------------------------
# Database Utility Functions
# -----------------------------------------------------------------------------
def init_db():
    """
    Initialize the SQLite database file if it does not exist.
    """
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        conn.close()

init_db()

def store_prediction_in_db(fixture_id, user_id, prediction, username):
    """
    For a given fixture_id, store (or update) the user's prediction along with their username.
    A table named "fixture_<fixture_id>" is used. If it does not exist, it is created.
    Columns:
      - user_id: INTEGER PRIMARY KEY
      - prediction: TEXT
      - username: TEXT
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    table_name = f"fixture_{fixture_id}"
    create_table_query = f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            user_id INTEGER PRIMARY KEY,
            prediction TEXT,
            username TEXT
        )
    """
    c.execute(create_table_query)
    insert_query = f"""
        INSERT OR REPLACE INTO "{table_name}" (user_id, prediction, username)
        VALUES (?, ?, ?)
    """
    c.execute(insert_query, (user_id, prediction, username))
    conn.commit()
    conn.close()

# -----------------------------------------------------------------------------
# User JSON Storage Utility
# -----------------------------------------------------------------------------
def update_user_json(user_id, fixture_id, match_name, prediction, username):
    """
    Update the user's JSON file by adding or replacing an entry in the "predictions"
    dictionary. Here we also store the username along with the prediction.
    """
    if not os.path.exists(USERS_DIR):
        os.makedirs(USERS_DIR)
    user_file = os.path.join(USERS_DIR, f"{user_id}.json")
    if os.path.exists(user_file):
        try:
            with open(user_file, "r") as f:
                user_data = json.load(f)
        except Exception:
            user_data = {"user_id": user_id}
    else:
        user_data = {"user_id": user_id}
    if "predictions" not in user_data:
        user_data["predictions"] = {}
    user_data["predictions"][str(fixture_id)] = {
        "match": match_name,
        "prediction": prediction,
        "username": username
    }
    with open(user_file, "w") as f:
        json.dump(user_data, f, indent=4)

def store_prediction(user_id, fixture_id, match_name, prediction, username):
    """
    Store the user's prediction both in the SQLite database and in the user's JSON file,
    including the username.
    """
    store_prediction_in_db(fixture_id, user_id, prediction, username)
    update_user_json(user_id, fixture_id, match_name, prediction, username)

# -----------------------------------------------------------------------------
# Bot Command Handlers
# -----------------------------------------------------------------------------
def register_user_handlers(bot):
    """
    Registers the base user handlers, including /start. Also calls register_user_extra_handlers
    to add the My Fixtures, Profile, FAQ, and Administration features.
    """
    @bot.message_handler(commands=["start"])
    def start_handler(message):
        user_id = message.from_user.id
        username = message.from_user.username
        
        if not username:
            bot.reply_to(
                message,
                "🚫 Oops! You need to set a username in your Telegram profile first. Then restart with /start."
            )
            return

        # Create the users folder if it doesn't exist.
        if not os.path.exists(USERS_DIR):
            os.makedirs(USERS_DIR)
        user_file = os.path.join(USERS_DIR, f"{user_id}.json")
        
        if os.path.exists(user_file):
            try:
                with open(user_file, "r") as f:
                    user_data = json.load(f)
            except Exception:
                user_data = {"user_id": user_id, "username": username}
        else:
            user_data = {"user_id": user_id, "username": username}
        
        if "predictions" not in user_data:
            user_data["predictions"] = {}
            
        user_data["username"] = username  # Ensure we store the up-to-date username
        with open(user_file, "w") as f:
            json.dump(user_data, f, indent=4)
        
        text = (
            f"🎉 Hey {username}! Welcome to Super Fantasy Football ⚽\n\n"
            "Predict match scores, climb the leaderboard, and become the ultimate football guru. "
            "Choose an option below to get started!"
        )
        markup = types.InlineKeyboardMarkup()
        btn_play = types.InlineKeyboardButton("🎮 Play", callback_data="user_play")
        btn_myfixtures = types.InlineKeyboardButton("📋 My Fixtures", callback_data="user_myfixtures")
        btn_profile = types.InlineKeyboardButton("👤 Profile", callback_data="user_profile")
        btn_admin = types.InlineKeyboardButton("🔧 Administration", callback_data="user_administration")
        btn_faq = types.InlineKeyboardButton("❓ FAQ", callback_data="user_faq")
        markup.row(btn_play, btn_myfixtures)
        markup.row(btn_profile, btn_admin)
        markup.add(btn_faq)
        bot.send_message(message.chat.id, text, reply_markup=markup)

    # ----------------------------
    # Register all the "extras" callbacks 
    # (My Fixtures, Profile, FAQ, Administration)
    # from user_extras.py
    # ----------------------------
    from user_extras import register_user_extra_handlers
    register_user_extra_handlers(bot)
