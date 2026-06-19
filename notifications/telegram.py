import os
import requests
import threading
import time
from typing import Optional
from notifications.base import NotifierBase, NotificationEvent

class TelegramNotifier(NotifierBase):
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        
    @property
    def name(self) -> str:
        return "Telegram"
        
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)
        
    def _format_message(self, event: NotificationEvent) -> str:
        emojis = {
            "TRADE_ENTRY": "📈",
            "TRADE_EXIT": "📉",
            "STOP_LOSS": "🛑",
            "DAILY_SUMMARY": "📊",
            "RISK_ALERT": "⚠️",
            "SYSTEM_ALERT": "🔴",
            "KILL_SWITCH": "🚨",
            "SCREENER_RESULT": "🔍"
        }
        
        emoji = emojis.get(event.event_type, "ℹ️")
        
        msg = f"{emoji} <b>{event.title}</b>\n\n{event.message}"
        if event.symbol:
            msg += f"\n<b>Symbol:</b> {event.symbol}"
            
        time_str = event.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        msg += f"\n\n<i>{time_str}</i>"
        
        if len(msg) > 4096:
            msg = msg[:4093] + "..."
            
        return msg
        
    def _send_sync(self, msg: str):
        if not self.is_configured():
            return
            
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": msg,
            "parse_mode": "HTML"
        }
        
        for attempt in range(3):
            try:
                response = requests.post(url, json=payload, timeout=5)
                if response.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
            
    def send(self, event: NotificationEvent) -> bool:
        if not self.is_configured():
            return False
            
        msg = self._format_message(event)
        
        # Run in background thread
        thread = threading.Thread(target=self._send_sync, args=(msg,), daemon=True)
        thread.start()
        
        return True
