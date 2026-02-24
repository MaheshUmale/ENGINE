import datetime

class RiskManager:
    def __init__(self, max_daily_loss=50000, max_positions=4):
        self.max_daily_loss = max_daily_loss
        self.max_positions = max_positions
        self.daily_pnl = 0
        self.current_date = None

    def recover_pnl(self):
        """
        Recovers today's realized PnL from the database.
        """
        from .database import get_session, Trade
        from sqlalchemy import func
        import datetime

        session = get_session()
        try:
            today = datetime.date.today()
            # Start of day UTC
            sod = datetime.datetime.combine(today, datetime.time.min)

            pnl_sum = session.query(func.sum(Trade.pnl)).filter(
                Trade.status == 'CLOSED',
                Trade.timestamp >= sod
            ).scalar()

            self.daily_pnl = float(pnl_sum) if pnl_sum else 0.0
            self.current_date = today
            if self.daily_pnl != 0:
                print(f"State Recovery: Recovered today's realized PnL: {self.daily_pnl:.2f}")
        except Exception as e:
            print(f"Error recovering PnL: {e}")
        finally:
            session.close()

    def reset_if_new_day(self, timestamp=None):
        if timestamp:
            date = timestamp.date() if hasattr(timestamp, 'date') else timestamp
        else:
            date = datetime.date.today()

        if self.current_date != date:
            self.current_date = date
            self.daily_pnl = 0

    def can_trade(self, current_positions_count, timestamp=None):
        self.reset_if_new_day(timestamp)

        if self.daily_pnl <= -self.max_daily_loss:
            return False, "Max Daily Loss reached"

        if current_positions_count >= self.max_positions:
            return False, f"Max Positions ({self.max_positions}) reached"

        return True, "Success"

    def update_pnl(self, trade_pnl):
        self.daily_pnl += trade_pnl
