import os
import json
import sqlite3
import io
from telebot import types

USER_STATS_DB = "users_datab.db"  # Database for overall user stats
USERS_DIR = "users"               # Folder with user JSON files
DB_FILE = "predictions.db"        # Predictions DB (fixture_<id> tables)

def register_user_extra_handlers(bot):
    """
    Register callback handlers for additional user features:
      - My Fixtures: Show upcoming/in-progress matches from user's JSON.
      - Profile: Show user's overall stats and provide a Download Predictions button.
      - Administration: Provide help/contact info.
      - FAQ: Describe how the bot works.
    """

    @bot.callback_query_handler(func=lambda call: call.data == "user_myfixtures")
    def user_myfixtures_callback(call):
        user_id = call.from_user.id
        user_file = os.path.join(USERS_DIR, f"{user_id}.json")
        lines = []
        if not os.path.exists(user_file):
            lines.append("⚠️ You have no recorded predictions yet.")
        else:
            try:
                with open(user_file, "r") as f:
                    user_data = json.load(f)
                predictions = user_data.get("predictions", {})
                upcoming = []
                for fx_id, fx_info in predictions.items():
                    # Consider fixtures without final_score as upcoming/in-progress
                    if "final_score" not in fx_info:
                        match_name = fx_info.get("match", "Unknown Match")
                        user_pred = fx_info.get("prediction", "?-?")
                        upcoming.append((fx_id, match_name, user_pred))
                if not upcoming:
                    lines.append("✅ You have no upcoming or in-progress matches.")
                else:
                    lines.append("<b>Your Upcoming/In-Progress Fixtures</b>\n")
                    for (fid, mname, pred) in upcoming:
                        lines.append(f"• <b>{mname}</b> | Your Prediction: <b>{pred}</b> (FixtureID: {fid})")
            except:
                lines.append("⚠️ Unable to read your predictions file.")
        text = "\n".join(lines)
        markup = types.InlineKeyboardMarkup()
        btn_back = types.InlineKeyboardButton("🔙 Back", callback_data="user_main_menu")
        markup.add(btn_back)
        try:
            bot.edit_message_text(chat_id=call.message.chat.id,
                                  message_id=call.message.message_id,
                                  text=text, parse_mode="HTML", reply_markup=markup)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        try:
            bot.answer_callback_query(call.id)
        except:
            pass

    @bot.callback_query_handler(func=lambda call: call.data == "user_profile")
    def user_profile_callback(call):
        user_id = call.from_user.id
        stats = _get_user_stats(user_id)
        if stats is None:
            text = (
                "👤 <b>Your Profile</b>\n\n"
                "No record found in stats database yet.\n"
                "Play some matches to get a rank!"
            )
        else:
            (won, lost, pts, rank, total_users) = stats
            text = (
                f"👤 <b>Your Profile</b>\n\n"
                f"• <b>Points:</b> {pts}\n"
                f"• <b>Wins:</b> {won}\n"
                f"• <b>Losses:</b> {lost}\n"
                f"• <b>Rank:</b> {rank} / {total_users}"
            )
        markup = types.InlineKeyboardMarkup()
        btn_download = types.InlineKeyboardButton("⬇️ Download Predictions", callback_data="download_user_predictions")
        btn_back = types.InlineKeyboardButton("🔙 Back", callback_data="user_main_menu")
        markup.row(btn_download)
        markup.add(btn_back)
        try:
            bot.edit_message_text(chat_id=call.message.chat.id,
                                  message_id=call.message.message_id,
                                  text=text, parse_mode="HTML", reply_markup=markup)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        try:
            bot.answer_callback_query(call.id)
        except:
            pass

    @bot.callback_query_handler(func=lambda call: call.data == "download_user_predictions")
    def download_user_predictions_callback(call):
        user_id = call.from_user.id
        user_file = os.path.join(USERS_DIR, f"{user_id}.json")
        if not os.path.exists(user_file):
            try:
                bot.answer_callback_query(call.id)
            except:
                pass
            bot.send_message(call.message.chat.id, "⚠️ You have no predictions to download.")
            return
        try:
            with open(user_file, "r") as f:
                user_data = json.load(f)
        except:
            bot.send_message(call.message.chat.id, "⚠️ Error reading your predictions file.")
            return
        preds = user_data.get("predictions", {})
        lines = []
        lines.append("Your Full Predictions:\n")
        for fid, info in preds.items():
            match_name = info.get("match", "Unknown")
            user_pred = info.get("prediction", "?-?")
            final_score = info.get("final_score")
            if final_score:
                comment = _compare_prediction(user_pred, final_score)
                lines.append(f"Fixture {fid}: {match_name}\n"
                             f"  Your Prediction: {user_pred}\n"
                             f"  Final Score: {final_score}\n"
                             f"  Result: {comment}\n")
            else:
                lines.append(f"Fixture {fid}: {match_name}\n"
                             f"  Your Prediction: {user_pred}\n"
                             f"  Final Score: Not finished\n"
                             f"  Result: TBD\n")
            lines.append("-----")
        file_text = "\n".join(lines)
        memfile = io.BytesIO(file_text.encode("utf-8"))
        memfile.name = "Your_Predictions.txt"
        try:
            bot.send_document(chat_id=call.message.chat.id,
                              document=memfile,
                              visible_file_name="Your_Predictions.txt",
                              caption="Here are all your predictions!")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"⚠️ Could not send file: {e}")
        _return_to_main_menu(bot, call)

    @bot.callback_query_handler(func=lambda call: call.data == "user_administration")
    def user_administration_callback(call):
        text = (
            "🔧 <b>Administration / Help</b>\n\n"
            "If you have any queries or need assistance, please contact our admin at @YourAdmin.\n"
            "We're here to help and keep the game running smoothly!"
        )
        markup = types.InlineKeyboardMarkup()
        btn_back = types.InlineKeyboardButton("🔙 Back", callback_data="user_main_menu")
        markup.add(btn_back)
        try:
            bot.edit_message_text(chat_id=call.message.chat.id,
                                  message_id=call.message.message_id,
                                  text=text, parse_mode="HTML", reply_markup=markup)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        try:
            bot.answer_callback_query(call.id)
        except:
            pass

    @bot.callback_query_handler(func=lambda call: call.data == "user_faq")
    def user_faq_callback(call):
        text = (
            "<b>❓ FAQ - How It Works</b>\n\n"
            "1. <b>Predicting Matches:</b> Tap 'Play' and select a fixture to predict its score.\n\n"
            "2. <b>Viewing Fixtures:</b> Use 'My Fixtures' to see your upcoming or in-progress matches.\n\n"
            "3. <b>Your Profile:</b> View your overall stats (points, wins, losses, rank) and download your predictions.\n\n"
            "4. <b>Live Updates:</b> You will receive live score updates both via DM and in the group chat.\n\n"
            "5. <b>Match Results:</b> Once a match finishes, you'll get a final result along with your performance stats.\n\n"
            "Need more help? Contact our admin at @YourAdmin."
        )
        markup = types.InlineKeyboardMarkup()
        btn_back = types.InlineKeyboardButton("🔙 Back", callback_data="user_main_menu")
        markup.add(btn_back)
        try:
            bot.edit_message_text(chat_id=call.message.chat.id,
                                  message_id=call.message.message_id,
                                  text=text, parse_mode="HTML", reply_markup=markup)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)
        try:
            bot.answer_callback_query(call.id)
        except:
            pass

# ---------------------------
# Internal helper functions for user_extras.py
# ---------------------------
def _return_to_main_menu(bot, call):
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    user_id = call.from_user.id
    user_file = os.path.join(USERS_DIR, f"{user_id}.json")
    username = "Player"
    if os.path.exists(user_file):
        try:
            with open(user_file, "r") as f:
                data = json.load(f)
            username = data.get("username", "Player")
        except:
            pass
    text = (
        f"👋 Hey {username}! Welcome back to <b>Super Fantasy Football</b> ⚽\n\n"
        "What would you like to do next?"
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
        bot.edit_message_text(chat_id=call.message.chat.id,
                              message_id=call.message.message_id,
                              text=text, parse_mode="HTML", reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)

def _get_user_stats(user_id):
    """
    Returns (won, lost, pts, rank, total_users) for the given user_id from the users table in users_datab.db.
    If the user isn't found, returns None.
    """
    db_path = USER_STATS_DB
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not c.fetchone():
        conn.close()
        return None
    c.execute("SELECT user_id, won, lost, pts FROM users")
    all_rows = c.fetchall()
    if not all_rows:
        conn.close()
        return None
    sorted_data = sorted(all_rows, key=lambda x: (-x[3], x[0]))  # sort by pts DESC, then user_id ASC
    rank = 1
    found = None
    for row in sorted_data:
        if row[0] == user_id:
            found = (row[1], row[2], row[3], rank, len(sorted_data))
            break
        rank += 1
    conn.close()
    return found

def _compare_prediction(pred_str, final_str):
    """
    Compares the user's prediction and the final score.
    Returns "WON" if they match exactly, otherwise "LOST".
    """
    try:
        p = pred_str.replace(" ", "").split("-")
        p_home = int(p[0])
        p_away = int(p[1])
    except:
        return "Invalid Prediction"
    try:
        f = final_str.replace(" ", "").split("-")
        f_home = int(f[0])
        f_away = int(f[1])
    except:
        return "Invalid Final Score"
    return "WON" if (p_home == f_home and p_away == f_away) else "LOST"
