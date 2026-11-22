import os
import requests

token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

message = (
    "🟢 Zealy Hunter is connected!\n\n"
    "Your Web3 discovery bot is being set up."
)

url = f"https://api.telegram.org/bot{token}/sendMessage"

response = requests.post(
    url,
    json={"chat_id": chat_id, "text": message},
    timeout=20
)

response.raise_for_status()
print("Telegram test message sent successfully.")
