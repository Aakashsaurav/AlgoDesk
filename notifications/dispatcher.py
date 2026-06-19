import threading
import logging
from typing import List, Optional
from notifications.base import NotifierBase, NotificationEvent, NotificationPriority
from notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

class NotificationDispatcher:
    def __init__(self, notifiers: List[NotifierBase]):
        self.notifiers = notifiers
        self.min_priority = NotificationPriority.INFO
        self.disabled_notifiers = set()
        
    def set_min_priority(self, priority: NotificationPriority):
        self.min_priority = priority
        
    def enable(self, notifier_name: str):
        if notifier_name in self.disabled_notifiers:
            self.disabled_notifiers.remove(notifier_name)
            
    def disable(self, notifier_name: str):
        self.disabled_notifiers.add(notifier_name)
        
    def dispatch(self, event: NotificationEvent):
        try:
            priorities = [NotificationPriority.INFO, NotificationPriority.WARNING, NotificationPriority.CRITICAL]
            if priorities.index(event.priority) < priorities.index(self.min_priority):
                return
                
            for notifier in self.notifiers:
                if notifier.name in self.disabled_notifiers:
                    continue
                if not notifier.is_configured():
                    continue
                    
                try:
                    notifier.send(event)
                except Exception as e:
                    logger.error(f"Failed to send notification via {notifier.name}: {e}")
        except Exception as e:
            logger.error(f"Error in dispatcher: {e}")
            
    def dispatch_async(self, event: NotificationEvent):
        thread = threading.Thread(target=self.dispatch, args=(event,), daemon=True)
        thread.start()

_dispatcher: Optional[NotificationDispatcher] = None

def _build_dispatcher_from_config() -> NotificationDispatcher:
    return NotificationDispatcher([
        TelegramNotifier()
    ])

def get_dispatcher() -> NotificationDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _build_dispatcher_from_config()
    return _dispatcher

def notify(event_type: str, title: str, message: str, priority=NotificationPriority.INFO, **kwargs):
    """One-liner notification from anywhere in the codebase."""
    get_dispatcher().dispatch_async(
        NotificationEvent(event_type=event_type, title=title, message=message, priority=priority, **kwargs)
    )

def send_daily_summary(state) -> None:
    """Builds daily P&L summary from LiveState and dispatches it."""
    trades = state.get_closed_trades()
    pnl = sum(t.pnl for t in trades)
    win_trades = sum(1 for t in trades if t.pnl > 0)
    total_trades = len(trades)
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    
    msg = f"📊 Daily P&L: ₹{pnl:+.2f} | Trades: {total_trades} | Win Rate: {win_rate:.1f}%"
    
    notify("DAILY_SUMMARY", "End of Day Summary", msg, priority=NotificationPriority.INFO)
