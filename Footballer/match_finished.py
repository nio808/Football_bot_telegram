import os
import json
import sqlite3

FIXED_MATCHES_FILE = "FixedMatches.json"
DB_FILE = "predictions.db"
USERS_DIR = "users"
USER_STATS_DB = "users_datab.db"
CONFIG_FILE = "config.json"

def process_finished_match(bot, fixture_id, home_goals, away_goals, counts):
    """
    Updated finalizing logic:
      1) remove match from FixedMatches.json
      2) broadcast final result to each user (DM)
      3) in the group, show final result plus how many got it correct & how many didn't
         also show the existing home/away/draw counts from 'counts'
      4) update user JSON with final_score
      5) track user stats in users_datab.db
    """
    match_data = _get_fixed_match(fixture_id)
    if not match_data:
        return

    home_name = match_data["home"]["name"]
    away_name = match_data["away"]["name"]

    text_template = (
        f"🏁 <b>The match {home_name} vs {away_name} has finished!</b>\n"
        f"Final Score: <b>{home_goals} - {away_goals}</b>\n"
        f"Your Prediction: <b>{{pred}}</b>\n\n"
        "Thanks for playing!"
    )

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    table_name = f"fixture_{fixture_id}"
    c.execute("""SELECT name FROM sqlite_master 
                 WHERE type='table' AND name=?""", (table_name,))
    table_exists = c.fetchone()

    correct_count = 0
    incorrect_count = 0

    if table_exists:
        c.execute(f'SELECT user_id, prediction FROM "{table_name}"')
        rows = c.fetchall()
        for (user_id, user_prediction) in rows:
            # DM the user final scoreboard
            final_text = text_template.format(pred=user_prediction)
            try:
                bot.send_message(user_id, final_text, parse_mode="HTML")
            except:
                pass

            # Save the final score in the user's JSON
            _update_user_json_final_score(user_id, fixture_id, home_goals, away_goals)

            # Check if correct
            h, a = _parse_prediction(user_prediction)
            if h == home_goals and a == away_goals:
                correct_count += 1
                result_type = "won"
            else:
                incorrect_count += 1
                result_type = "lost"

            # Update user stats in users_datab.db
            username = _get_username_from_json(user_id) or f"User{user_id}"
            _update_user_stats_db(user_id, username, result_type)
    conn.close()

    # Remove from FixedMatches.json
    _remove_from_fixed_matches(fixture_id)

    # Announce final to the group
    group_id = _read_group_id()
    if group_id:
        c_home = counts.get("home", 0)
        c_away = counts.get("away", 0)
        c_draw = counts.get("draw", 0)
        group_text = (
            f"🏁 <b>{home_name} vs {away_name}</b> just finished!\n"
            f"Final Score: <b>{home_goals} - {away_goals}</b>\n"
            f"Home Predictions: {c_home}\n"
            f"Away Predictions: {c_away}\n"
            f"Draw Predictions: {c_draw}\n\n"
            f"Won 👑: <b>{correct_count}</b>  |  Lost 🔴: <b>{incorrect_count}</b>"
        )
        try:
            bot.send_message(group_id, group_text, parse_mode="HTML")
        except Exception as e:
            print(f"[match_finished WARNING] Could not broadcast final to group {group_id}: {e}")

# ---------------------------
# Internal helpers
# ---------------------------
def _remove_from_fixed_matches(fixture_id):
    if not os.path.exists(FIXED_MATCHES_FILE):
        return
    try:
        with open(FIXED_MATCHES_FILE, "r") as f:
            data = json.load(f)
        new_data = [m for m in data if str(m["fixture_id"]) != str(fixture_id)]
        with open(FIXED_MATCHES_FILE, "w") as f:
            json.dump(new_data, f, indent=4)
    except:
        pass

def _get_fixed_match(fixture_id):
    if not os.path.exists(FIXED_MATCHES_FILE):
        return None
    try:
        with open(FIXED_MATCHES_FILE, "r") as f:
            data = json.load(f)
        for item in data:
            if str(item["fixture_id"]) == str(fixture_id):
                return item
    except:
        pass
    return None

def _update_user_json_final_score(user_id, fixture_id, home_goals, away_goals):
    user_file = os.path.join(USERS_DIR, f"{user_id}.json")
    if not os.path.exists(user_file):
        return
    try:
        with open(user_file, "r") as f:
            user_data = json.load(f)
    except:
        return
    preds = user_data.get("predictions", {})
    key = str(fixture_id)
    if key not in preds:
        return
    preds[key]["final_score"] = f"{home_goals} - {away_goals}"
    with open(user_file, "w") as f:
        json.dump(user_data, f, indent=4)

def _parse_prediction(pred_str):
    try:
        parts = pred_str.replace(" ", "").split("-")
        h = int(parts[0])
        a = int(parts[1])
        return (h, a)
    except:
        return (0, 0)

def _get_username_from_json(user_id):
    user_file = os.path.join(USERS_DIR, f"{user_id}.json")
    if not os.path.exists(user_file):
        return None
    try:
        with open(user_file, "r") as f:
            data = json.load(f)
        return data.get("username")
    except:
        return None

# ---------------------------
# Stats DB
# ---------------------------
def _init_users_db():
    conn = sqlite3.connect(USER_STATS_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            won INTEGER DEFAULT 0,
            lost INTEGER DEFAULT 0,
            pts INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def _update_user_stats_db(user_id, username, result_type):
    _init_users_db()
    conn = sqlite3.connect(USER_STATS_DB)
    c = conn.cursor()

    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("""
            INSERT INTO users (user_id, username, won, lost, pts)
            VALUES (?, ?, 0, 0, 0)
        """, (user_id, username))
        conn.commit()

    if result_type == "won":
        c.execute("""
            UPDATE users
               SET won = won + 1,
                   pts = pts + 5,
                   username=?
             WHERE user_id=?
        """, (username, user_id))
    else:
        c.execute("""
            UPDATE users
               SET lost = lost + 1,
                   username=?
             WHERE user_id=?
        """, (username, user_id))

    conn.commit()
    conn.close()

def _read_group_id():
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r") as f:
            conf = json.load(f)
        return conf.get("groupid")
    except:
        return None
