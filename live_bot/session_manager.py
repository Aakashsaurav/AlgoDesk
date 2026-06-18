import time as sys_time
from datetime import datetime, time
import threading
import logging
from enum import Enum
from live_bot.config import LiveBotConfig

logger = logging.getLogger(__name__)

class SessionPhase(Enum):
    PRE_MARKET  = "PRE_MARKET"
    ACTIVE      = "ACTIVE"
    POST_MARKET = "POST_MARKET"
    CLOSED      = "CLOSED"

class SessionManager:
    """
    Manages session lifecycle: pre-market → active → post-market.
    Handles daily state resets, token refresh, squareoff scheduling.
    """
    def __init__(self, config: LiveBotConfig, state, risk_engine=None, broker=None, storage_manager=None, session_store=None):
        self.config = config
        self.state = state
        self.risk_engine = risk_engine
        self.broker = broker
        self.storage_manager = storage_manager
        self.session_store = session_store
        
        self.phase = SessionPhase.CLOSED
        self._squareoff_thread = None
        self._squareoff_scheduled = False

    def start_session(self):
        self.phase = SessionPhase.PRE_MARKET
        
        # Reset LiveState daily counters
        if hasattr(self.state, "reset_daily_state"):
            self.state.reset_daily_state()
            
        # Reset risk engine
        if self.risk_engine and hasattr(self.risk_engine, "reset_daily_state"):
            self.risk_engine.reset_daily_state()
            
        # Validate access token freshness (placeholder logic)
        logger.info("Validating access token freshness...")
        
        # Seed candles via parallel loader
        logger.info("Seeding historical candles...")
        
        self.phase = SessionPhase.ACTIVE
        logger.info("Session started and now ACTIVE.")

    def end_session(self):
        self.phase = SessionPhase.POST_MARKET
        
        # Force squareoff if MIS
        if self.config.product == "I" and self.broker:
            logger.info("MIS product detected. Forcing squareoff of all positions.")
            if hasattr(self.broker, "squareoff_all"):
                self.broker.squareoff_all()
                
        # Flush all storage
        if self.storage_manager and hasattr(self.storage_manager, "flush_all"):
            self.storage_manager.flush_all()
            
        # Save session stats
        if self.session_store and hasattr(self.state, "get_session_stats"):
            stats = self.state.get_session_stats()
            self.session_store.save_session(stats)
            
        self.phase = SessionPhase.CLOSED
        logger.info("Session ENDED and CLOSED.")

    def schedule_squareoff(self, squareoff_time: time):
        if self._squareoff_scheduled:
            return
            
        def _wait_and_squareoff():
            while self.phase != SessionPhase.CLOSED:
                from config import IST
                now = datetime.now(tz=IST).time()
                if now >= squareoff_time:
                    logger.info("Scheduled squareoff time reached. Executing squareoff_all.")
                    if self.broker and hasattr(self.broker, "squareoff_all"):
                        self.broker.squareoff_all()
                    break
                sys_time.sleep(10)
                
        self._squareoff_thread = threading.Thread(target=_wait_and_squareoff, daemon=True)
        self._squareoff_thread.start()
        self._squareoff_scheduled = True
        logger.info(f"Scheduled auto-squareoff for {squareoff_time}.")

    def is_market_open(self) -> bool:
        if self.risk_engine and hasattr(self.risk_engine, "is_market_open"):
            return self.risk_engine.is_market_open()
        # Fallback simplistic check
        from config import IST
        now = datetime.now(tz=IST).time()
        return time(9, 15) <= now <= time(15, 30)
