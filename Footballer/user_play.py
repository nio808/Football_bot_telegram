import os
import json
from datetime import datetime, timezone
import telebot
from telebot import types
from userhandler import store_prediction  # Import our updated storage function (now accepts username)

# Global dictionary to store a user’s pending prediction for a match.
# Key: (user_id, fixture_id) → Value: {"team1": <score>, "team2": <score>}
PENDING_PREDICTIONS = {}

FIXED_MATCHES_FILE = "FixedMatches.json"  # Fixed matches set by admins.
FIXTURES_DIR = "fixtures"                # Folder where match predictions are stored.
USERS_DIR = "users"                      # Folder where user data is stored.

# ─── UTILITY FUNCTIONS ──────────────────────────────────────────────

def load_fixed_matches():
    """Load the list of fixed matches from FixedMatches.json."""
    if os.path.exists(FIXED_MATCHES_FILE):
        try:
            with open(FIXED_MATCHES_FILE, "r") as f:
                return json.load(f)  # Expecting a list of match dicts.
        except Exception:
            return []
    return []

def get_match_by_fixture(fixture_id):
    """Find a fixed match (from FixedMatches.json) by its fixture_id."""
    matches = load_fixed_matches()
    for match in matches:
        if str(match.get("fixture_id")) == str(fixture_id):
            return match
    return None

def has_user_predicted(user_id, fixture_id):
    """
    Checks the user's JSON file (in the users folder) to see if a prediction
    for the given fixture (identified by fixture_id) already exists.
    """
    user_file = os.path.join(USERS_DIR, f"{user_id}.json")
    if os.path.exists(user_file):
        try:
            with open(user_file, "r") as f:
                user_data = json.load(f)
            predictions = user_data.get("predictions", {})
            return str(fixture_id) in predictions
        except Exception:
            return False
    return False

# ─── MENU DISPLAY FUNCTIONS ─────────────────────────────────────────

def show_play_menu(bot, call):
    """
    Display an inline list of fixed matches (from FixedMatches.json) so the user can select one
    to predict. Matches already predicted by the user will show a red emoji.
    """
    user_id = call.from_user.id
    fixed_matches = load_fixed_matches()
    markup = types.InlineKeyboardMarkup()
    text = "🎮 Select a match to predict:"
    if not fixed_matches:
        text = "⚠️ No matches available for prediction at the moment."
    else:
        for match in fixed_matches:
            fixture_id = match.get("fixture_id")  # Unique identifier.
            match_date = datetime.fromtimestamp(match["timestamp"] + 30, timezone.utc).strftime("%d %b")
            home_team = match["home"]["name"]
            away_team = match["away"]["name"]
            button_text = f"📆 {match_date}: {home_team} vs {away_team}"
            if has_user_predicted(user_id, fixture_id):
                button_text += " 🔴"
            btn = types.InlineKeyboardButton(button_text, callback_data=f"play_match:{fixture_id}")
            markup.add(btn)
    btn_back = types.InlineKeyboardButton("🔙 Back", callback_data="user_main_menu")
    markup.add(btn_back)
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=markup
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup)
    bot.answer_callback_query(call.id)

def show_prediction_keyboard(bot, chat_id, message_id, team_name, step, fixture_id):
    """
    Displays an inline keyboard for the user to pick a score (0 to 10) for a given team.
    
    Parameters:
      - team_name: Name of the team (for display).
      - step: "team1" or "team2" indicating which team's score is being predicted.
      - fixture_id: The fixed match’s fixture_id.
    """
    text = f"🔢 Predict the score for <b>{team_name}</b>:"
    markup = types.InlineKeyboardMarkup()
    row = []
    for num in range(0, 11):
        if step == "team1":
            cb_data = f"predict_team1:{num}:{fixture_id}"
        else:
            cb_data = f"predict_team2:{num}:{fixture_id}"
        btn = types.InlineKeyboardButton(str(num), callback_data=cb_data)
        row.append(btn)
        if len(row) == 3:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
    btn_back = types.InlineKeyboardButton("🔙 Back", callback_data="user_play")
    markup.add(btn_back)
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception:
        bot.send_message(chat_id, text, reply_markup=markup)

def finalize_prediction(bot, user_id, chat_id, message_id, fixture_id):
    """
    After both team scores have been chosen, display the final prediction and store it.
    The prediction is stored in the fixtures folder and the user's JSON file.
    Additionally, the prediction (along with the user's username) is recorded in the
    SQLite database via store_prediction.
    """
    pending = PENDING_PREDICTIONS.get((user_id, fixture_id))
    if not pending or "team1" not in pending or "team2" not in pending:
        return  # Something went wrong.
    team1_score = pending["team1"]
    team2_score = pending["team2"]
    match = get_match_by_fixture(fixture_id)
    if not match:
        bot.send_message(chat_id, "❌ Match data not found!")
        return
    home_team = match["home"]["name"]
    away_team = match["away"]["name"]
    final_text = (
        f"✅ You have predicted <b>{home_team}</b> vs <b>{away_team}</b>: <b>{team1_score} - {team2_score}</b>"
    )
    
    # Update the fixtures file as before.
    if not os.path.exists(FIXTURES_DIR):
        os.makedirs(FIXTURES_DIR)
    file_path = os.path.join(FIXTURES_DIR, f"{fixture_id}.json")
    data = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    if "match" not in data or "predictions" not in data:
        data["match"] = f"{home_team} vs {away_team}"
        data["predictions"] = {}
    data["predictions"][str(user_id)] = f"{team1_score} - {team2_score}"
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)
    
    # Update the user's JSON file.
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
        "match": f"{home_team} vs {away_team}",
        "prediction": f"{team1_score} - {team2_score}"
    }
    with open(user_file, "w") as f:
        json.dump(user_data, f, indent=4)
    
    # Get the user's username.
    try:
        chat_obj = bot.get_chat(user_id)
        username = chat_obj.username if chat_obj.username else "Player"
    except Exception:
        username = "Player"
    
    # Store the prediction in the database (including the username).
    store_prediction(user_id, fixture_id, f"{home_team} vs {away_team}", f"{team1_score} - {team2_score}", username)
    
    # Remove the pending prediction now that it’s finalized.
    PENDING_PREDICTIONS.pop((user_id, fixture_id), None)
    
    markup = types.InlineKeyboardMarkup()
    btn_main_menu = types.InlineKeyboardButton("🏠 Main Menu", callback_data="user_main_menu")
    btn_play_another = types.InlineKeyboardButton("🎮 Play Another", callback_data="user_play")
    markup.row(btn_play_another, btn_main_menu)
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=final_text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception:
        bot.send_message(chat_id, final_text, reply_markup=markup)

# ─── REGISTRATION OF PLAY HANDLERS ───────────────────────────────────

def register_user_play_handlers(bot):
    """Registers all callback handlers related to the Play flow."""
    
    @bot.callback_query_handler(func=lambda call: call.data == "user_play")
    def user_play_callback(call):
        show_play_menu(bot, call)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("play_match:"))
    def play_match_callback(call):
        user_id = call.from_user.id
        fixture_id = call.data.split(":", 1)[1]
        if has_user_predicted(user_id, fixture_id):
            bot.answer_callback_query(
                call.id,
                "⚠️ You've already chosen a prediction for this match!",
                show_alert=True
            )
            return
        PENDING_PREDICTIONS[(user_id, fixture_id)] = {}
        match = get_match_by_fixture(fixture_id)
        if not match:
            bot.answer_callback_query(call.id, "❌ Match data not found!")
            return
        home_team = match["home"]["name"]
        show_prediction_keyboard(
            bot,
            call.message.chat.id,
            call.message.message_id,
            home_team,
            "team1",
            fixture_id
        )
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("predict_team1:"))
    def predict_team1_callback(call):
        user_id = call.from_user.id
        parts = call.data.split(":")
        if len(parts) < 3:
            bot.answer_callback_query(call.id, "❌ Invalid callback data!")
            return
        score = parts[1]
        fixture_id = parts[2]
        key = (user_id, fixture_id)
        if key not in PENDING_PREDICTIONS:
            PENDING_PREDICTIONS[key] = {}
        PENDING_PREDICTIONS[key]["team1"] = score
        match = get_match_by_fixture(fixture_id)
        if not match:
            bot.answer_callback_query(call.id, "❌ Match data not found!")
            return
        away_team = match["away"]["name"]
        show_prediction_keyboard(
            bot,
            call.message.chat.id,
            call.message.message_id,
            away_team,
            "team2",
            fixture_id
        )
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("predict_team2:"))
    def predict_team2_callback(call):
        user_id = call.from_user.id
        parts = call.data.split(":")
        if len(parts) < 3:
            bot.answer_callback_query(call.id, "❌ Invalid callback data!")
            return
        score = parts[1]
        fixture_id = parts[2]
        key = (user_id, fixture_id)
        if key not in PENDING_PREDICTIONS or "team1" not in PENDING_PREDICTIONS[key]:
            bot.answer_callback_query(call.id, "❌ Something went wrong!")
            return
        PENDING_PREDICTIONS[key]["team2"] = score
        finalize_prediction(bot, user_id, call.message.chat.id, call.message.message_id, fixture_id)
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data == "user_main_menu")
    def user_main_menu_callback(call):
        user_id = call.from_user.id
        user_file = os.path.join(USERS_DIR, f"{user_id}.json")
        username = "Player"
        if os.path.exists(user_file):
            try:
                with open(user_file, "r") as f:
                    data = json.load(f)
                    username = data.get("username", "Player")
            except Exception:
                pass
        text = (
            f"👋 Hey {username}! Welcome back to **Super Fantasy Football** ⚽\n\n"
            "Get ready to play, predict, and have a blast! What would you like to do next?"
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
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=markup,
                parse_mode="Markdown"
            )
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup)
        bot.answer_callback_query(call.id)
