import os
import json
import time
import threading
import requests
import sqlite3

from match_finished import process_finished_match

CONFIG_FILE = "config.json"
FIXED_MATCHES_FILE = "FixedMatches.json"
LIVE_MATCHES_FILE = "live_matches.json"
DB_FILE = "predictions.db"

def start_live_monitor(bot):
    """
    Starts a background thread that periodically calls the live odds API 
    and notifies users of score changes / final results.
    """
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
    apikey = config.get("apikey", "")
    tocheck = config.get("tocheck", 10)  # check interval in seconds

    thread = threading.Thread(
        target=_live_monitor_loop,
        args=(bot, apikey, tocheck),
        daemon=True
    )
    thread.start()

def _live_monitor_loop(bot, apikey, interval):
    """
    Continuously runs in the background, polling the local API every `interval` seconds.
    Checks which fixtures we have in FixedMatches.json, updates them if goals changed,
    and calls process_finished_match when a fixture is done.
    """
    while True:
        try:
            # 1. Make the API call
            url = "http://127.0.0.1:5000/odds/live?league=39"
            headers = {
                "x-apisports-key": apikey,
                "Accept": "application/json"
            }
            response = requests.get(url, headers=headers)
            data = response.json()

            # 2. Get our current list of fixed matches
            fixed_matches = _load_fixed_matches()
            fixed_index = {str(m["fixture_id"]): m for m in fixed_matches}

            # 3. Load or init local live data (which includes stored home/away/draw counts)
            if os.path.exists(LIVE_MATCHES_FILE):
                try:
                    with open(LIVE_MATCHES_FILE, "r") as f:
                        local_live_data = json.load(f)
                except:
                    local_live_data = {}
            else:
                local_live_data = {}

            # 4. Process each fixture in the API’s response
            live_items = data.get("response", [])
            for item in live_items:
                fixture_id = str(item["fixture"]["id"])
                if fixture_id not in fixed_index:
                    continue  # Not one of our tracked matches

                # Extract relevant info
                home_goals = item["teams"]["home"]["goals"]
                away_goals = item["teams"]["away"]["goals"]
                status_long = item["fixture"]["status"]["long"]  # e.g. "Halftime", "Match Finished"
                time_str = item["fixture"]["status"].get("seconds", "00:00")

                # If this fixture_id not in local data, it's our first time:
                # compute counts for home/away/draw once.
                if fixture_id not in local_live_data:
                    local_live_data[fixture_id] = {
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "counts": _calculate_prediction_counts(fixture_id)
                    }
                    # We can send an initial broadcast to group and users if you like:
                    _broadcast_score_update(
                        bot, fixture_id, home_goals, away_goals,
                        time_str, local_live_data[fixture_id]["counts"]
                    )
                else:
                    old_home = local_live_data[fixture_id].get("home_goals")
                    old_away = local_live_data[fixture_id].get("away_goals")
                    # If goals changed => broadcast
                    if home_goals != old_home or away_goals != old_away:
                        _broadcast_score_update(
                            bot, fixture_id, home_goals, away_goals,
                            time_str, local_live_data[fixture_id]["counts"]
                        )

                # Check if match is finished
                if status_long.lower() in ("match finished", "finished", "full time"):
                    # Let match_finished.py handle final logic. We pass the 'counts' dict.
                    counts = local_live_data.get(fixture_id, {}).get("counts", {})
                    process_finished_match(
                        bot, fixture_id, home_goals, away_goals, counts
                    )
                    # Remove from local tracking
                    if fixture_id in local_live_data:
                        del local_live_data[fixture_id]
                    continue

                # Otherwise, update local tracking with new scores
                local_live_data[fixture_id]["home_goals"] = home_goals
                local_live_data[fixture_id]["away_goals"] = away_goals

            # 5. Save updated local data
            with open(LIVE_MATCHES_FILE, "w") as f:
                json.dump(local_live_data, f, indent=4)

        except Exception as e:
            print(f"[live_monitor ERROR] {e}")

        time.sleep(interval)

def _load_fixed_matches():
    """Return the list of items in FixedMatches.json, or [] on error."""
    if not os.path.exists(FIXED_MATCHES_FILE):
        return []
    try:
        with open(FIXED_MATCHES_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def _broadcast_score_update(bot, fixture_id, home_goals, away_goals, time_str, counts):
    """
    Broadcast a *live score update* to:
      1) Each user who predicted this fixture (user-level DM).
      2) The group, showing how many predicted home/away/draw from `counts`.
    """
    match_data = _get_fixed_match(fixture_id)
    if not match_data:
        return

    home_name = match_data["home"]["name"]
    away_name = match_data["away"]["name"]

    # Build user-level message
    text_user = (
        f"⚽️ <b>Live Update for fixture #{fixture_id}</b>\n"
        f"<b>{home_name}</b> vs <b>{away_name}</b>\n"
        f"Score: <b>{home_goals} - {away_goals}</b>\n"
        f"Time: <b>{time_str}</b>"
    )
    # Build group-level message (add predictions count)
    c_home = counts.get("home", 0)
    c_away = counts.get("away", 0)
    c_draw = counts.get("draw", 0)

    text_group = (
        f"⚽️ <b>Live Update</b> for fixture #{fixture_id}\n"
        f"<b>{home_name}</b> vs <b>{away_name}</b>\n"
        f"Score: <b>{home_goals} - {away_goals}</b>  "
        f"| Time: <b>{time_str}</b>\n\n"
        f"<i>Prediction Counts:</i>\n"
        f"  • {home_name} Win: {c_home}\n"
        f"  • {away_name} Win: {c_away}\n"
        f"  • Draw: {c_draw}"
    )

    # 1. Send to users who predicted
    user_ids = _get_user_ids_for_fixture(fixture_id)
    for uid in user_ids:
        try:
            bot.send_message(uid, text_user, parse_mode="HTML")
        except Exception as e:
            print(f"[live_monitor WARNING] Could not send update to user {uid}: {e}")

    # 2. Send to group
    group_id = _read_group_id()
    if group_id:
        try:
            bot.send_message(group_id, text_group, parse_mode="HTML")
        except Exception as e:
            print(f"[live_monitor WARNING] Could not send update to group {group_id}: {e}")

def _calculate_prediction_counts(fixture_id):
    """
    Reads the table fixture_<fixture_id> in predictions.db, 
    for each user parse the prediction "X - Y":
      - if X>Y => home
      - if X<Y => away
      - if X==Y => draw
    Returns a dict like {"home": #, "away": #, "draw": #}
    """
    home_count = 0
    away_count = 0
    draw_count = 0

    table_name = f"fixture_{fixture_id}"
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Check table existence
    try:
        c.execute(f'SELECT user_id, prediction FROM "{table_name}"')
        rows = c.fetchall()
        for row in rows:
            pred_str = row[1]
            h, a = _parse_prediction(pred_str)
            if h > a:
                home_count += 1
            elif a > h:
                away_count += 1
            else:
                draw_count += 1
    except:
        pass
    conn.close()
    return {"home": home_count, "away": away_count, "draw": draw_count}

def _parse_prediction(pred_str):
    """
    e.g. "2 - 1" => (2,1). If parse error => (0,0).
    """
    try:
        parts = pred_str.replace(" ", "").split("-")
        h = int(parts[0])
        a = int(parts[1])
        return (h, a)
    except:
        return (0, 0)

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

def _get_user_ids_for_fixture(fixture_id):
    """
    Looks up user_ids by reading the table fixture_<fixture_id> in predictions.db.
    Returns a list of user_ids or an empty list if no table or no records.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    table_name = f'fixture_{fixture_id}'
    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
        (table_name,)
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return []
    c.execute(f'SELECT user_id FROM "{table_name}"')
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def _read_group_id():
    config_path = CONFIG_FILE
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, "r") as f:
            conf = json.load(f)
        return conf.get("groupid")
    except:
        return None
