import os
import json
import time
import threading
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- Load configuration from config.json ---
# Example config.json:
# {
#   "token": "YOUR_TELEGRAM_BOT_API_TOKEN",
#   "chatid": [123456789, 987654321],
#   "minimumbuy": 0.0003,
#   "emojiamount": 10
# }
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]
# Accept a single chat ID or a list of chat IDs.
CHAT_IDS = config["chatid"] if isinstance(config["chatid"], list) else [config["chatid"]]
MINIMUM_BUY = config["minimumbuy"]

bot = telebot.TeleBot(TOKEN)

# --- Persistent Storage for Processed Transactions ---
PROCESSED_FILE = "processed_transactions.json"
if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "r") as f:
        processed_transactions = json.load(f)
else:
    processed_transactions = []

def save_processed_transactions():
    with open(PROCESSED_FILE, "w") as f:
        json.dump(processed_transactions, f)

def check_new_transactions():
    url = "https://jokerdoge.com/api/v1/get-purchase-history"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print("Error: API call returned status", response.status_code)
            return

        data = response.json()

        # The API may return either a list of transactions or a single transaction dictionary.
        if isinstance(data.get("data"), list):
            transactions = data["data"]
        elif isinstance(data.get("data"), dict):
            transactions = [data["data"]]
        else:
            print("Unexpected data format from API")
            return

        for tx in transactions:
            if tx.get("purchaseTotal", 0) < MINIMUM_BUY:
                continue

            # Use a unique identifier for the transaction.
            tx_id = tx.get("_id") or tx.get("nativeTransactionHash")
            if tx_id in processed_transactions:
                continue

            processed_transactions.append(tx_id)
            save_processed_transactions()
            send_transaction(tx)

    except Exception as e:
        print("Exception during API call or processing:", e)

def send_transaction(tx):
    """
    Formats transaction data and sends the MP4 video with an attached caption.
    The caption is built as follows:

    <b><a href="https://t.me/+ilYg1VjXp4xhODAx">$JOGE Buy!</a></b>
    <dynamic dog emoji line based on purchaseTotal (dollar value) and emojiamount from config>

    💵  $<purchaseTotal> (<coinAmount> SOL)
    🐶  <tokenAmount> JOGE
    🧾  <b><a href="https://solscan.io/account/{walletAddress}">Buyer</a></b> | 
         <b><a href="https://solscan.io/tx/{nativeTxHash}">Tx</a></b>
    📈  Price $<pricePerCoin>

    <b><a href="https://jokerdoge.com/">Website</a></b> - 
    <b><a href="https://x.com/JokerdogeSol">X(Twitter)</a></b> - 
    <b><a href="https://jokerdoge.com/assets/joge.pdf-CGDTxqoe.pdf">Whitepaper</a></b>
    """
    # Extract API data
    purchaseTotal = tx.get("purchaseTotal", 0)
    coinAmount    = tx.get("coinAmount", 0)
    tokenAmount   = tx.get("tokenAmount", 0)
    pricePerCoin  = tx.get("pricePerCoin", 0)
    walletAddress = tx.get("walletAddress", "Unknown")
    nativeTxHash  = tx.get("nativeTransactionHash", "")

    # Fixed Telegram link for header.
    telegram_link = "https://t.me/+ilYg1VjXp4xhODAx"

    # --- Compute dynamic dog emoji line based on purchaseTotal (dollar value) ---
    # "emojiamount" determines how many dollars correspond to one dog emoji.
    emoji_value = config.get("emojiamount", 10)
    raw_emoji_count = purchaseTotal / emoji_value
    emoji_count = int(raw_emoji_count) if raw_emoji_count >= 1 else 1

    if emoji_count <= 20:
        emoji_line = "🐶" * emoji_count
    else:
        emoji_line = "🐶" * 20 + f" +{emoji_count - 20}"

    # Build the caption exactly as required.
    caption = (
        f'<b><a href="{telegram_link}">$JOGE Buy!</a></b>\n'
        f'{emoji_line}\n\n'
        f'💵  ${purchaseTotal:.2f} ({coinAmount} SOL)\n'
        f'🐶  {tokenAmount} JOGE\n'
        f'🧾  <b><a href="https://solscan.io/account/{walletAddress}">Buyer</a></b> | '
        f'<b><a href="https://solscan.io/tx/{nativeTxHash}">Tx</a></b>\n'
        f'📈  Price ${pricePerCoin:.6f}\n\n'
        f'<b><a href="https://jokerdoge.com/">Website</a></b> - '
        f'<b><a href="https://x.com/JokerdogeSol">X(Twitter)</a></b> - '
        f'<b><a href="https://jokerdoge.com/assets/joge.pdf-CGDTxqoe.pdf">Whitepaper</a></b>'
    )

    # --- Create Inline Keyboard with Two Buttons ---
    markup = InlineKeyboardMarkup()
    btn_buy = InlineKeyboardButton("Buy $JOGE", url="https://jokerdoge.com/")
    btn_stake = InlineKeyboardButton("Stake $JOGE", url="https://jokerdoge.com/")
    markup.row(btn_buy, btn_stake)

    try:
        for chat_id in CHAT_IDS:
            with open("animation.mp4", "rb") as video:
                bot.send_video(
                    chat_id,
                    video,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=markup
                )
    except Exception as e:
        print("Error sending message:", e)

def transaction_loop():
    """Continuously checks for new transactions every 10 seconds."""
    while True:
        check_new_transactions()
        time.sleep(10)  # Adjust the interval as needed

if __name__ == "__main__":
    # --- Start the Transaction Check Loop in a Separate Thread ---
    transaction_thread = threading.Thread(target=transaction_loop, daemon=True)
    transaction_thread.start()

    # --- Start Telegram Bot's Infinite Polling ---
    bot.infinity_polling()
