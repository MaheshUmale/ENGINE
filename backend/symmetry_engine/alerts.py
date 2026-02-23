import aiohttp
import os
import datetime
from .database import get_session, Notification, AppSetting

class AlertManager:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')

    def check_alerts_enabled(self):
        session = get_session()
        try:
            setting = session.query(AppSetting).filter_by(key='ENABLE_ALERTS').first()
            if setting and setting.value == 'True':
                return True
            # Default to True if not set
            if not setting:
                return True
            return False
        finally:
            session.close()

    async def send_notification(self, message):
        if not self.check_alerts_enabled():
            return

        print(f"ALERT: {message}")

        # Save to DB for dashboard
        session = get_session()
        try:
            notification = Notification(message=message, timestamp=datetime.datetime.utcnow())
            session.add(notification)
            session.commit()
        except Exception as e:
            print(f"Error saving notification to DB: {e}")
        finally:
            session.close()

        # Optional: Keep Telegram as secondary if configured, but prioritizing dashboard now
        if self.bot_token and self.chat_id:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            try:
                async with aiohttp.ClientSession() as session_http:
                    async with session_http.post(url, json=payload) as resp:
                        if resp.status != 200:
                            pass
            except Exception as e:
                print(f"Error sending telegram alert: {e}")
