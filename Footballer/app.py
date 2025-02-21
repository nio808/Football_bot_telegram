import telebot
import json
import time
from adminhandler import register_admin_handlers
from userhandler import register_user_handlers
from user_play import register_user_play_handlers
from live_monitor import start_live_monitor

# Load configuration from config.json
with open("config.json", "r") as f:
    config = json.load(f)

bot = telebot.TeleBot(config["bot_token"])

# Register handlers
register_admin_handlers(bot)
register_user_handlers(bot)
register_user_play_handlers(bot)
start_live_monitor(bot)

# Infinite polling loop with error handling
while True:
    try:
        bot.infinity_polling()
    except Exception as e:
        print("Bot polling failed, restarting in 5 seconds. Error:", e)
        time.sleep(5)
