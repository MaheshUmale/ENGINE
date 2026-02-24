from .database import get_session, Trade
from .config import INDICES
import datetime

class ExecutionEngine:
    def __init__(self, session_factory=None, initial_balance=1000000, slippage=0.001, commission_rate=0.0005, fixed_charge=20):
        self.get_session = session_factory or get_session
        self.balance = initial_balance
        self.slippage = slippage # 0.1% default
        self.commission_rate = commission_rate # 0.05%
        self.fixed_charge = fixed_charge # Flat INR 20 per trade
        self.positions = {} # index_name -> position

    def recover_positions(self):
        """
        Recovers open positions from the database on startup.
        """
        session = self.get_session()
        try:
            open_trades = session.query(Trade).filter_by(status='OPEN').all()
            for trade in open_trades:
                self.positions[trade.index_name] = {
                    'trade_id': trade.id,
                    'side': trade.instrument_key,
                    'entry_price': trade.price / (1 + self.slippage), # Reverse slippage for internal tracking
                    'quantity': trade.quantity,
                    'ce_key': trade.instrument_ce,
                    'pe_key': trade.instrument_pe,
                    'trailing_sl': trade.trailing_sl
                }

            if self.positions:
                print(f"State Recovery: Recovered {len(self.positions)} open positions.")
        except Exception as e:
            print(f"Error recovering positions: {e}")
        finally:
            session.close()

    def execute_signal(self, signal, timestamp=None, index_price=None):
        """
        Executes a signal by entering a paper trade.
        """
        if signal.index_name in self.positions:
            return None # Already in a position for this index

        # Apply slippage to entry price
        entry_price = signal.option_price * (1 + self.slippage)

        # Use proper lot size
        lot_size = INDICES.get(signal.index_name, {}).get('lot_size', 1)
        quantity = lot_size

        # Turnover-based commission + fixed charge
        entry_cost = (entry_price * quantity * self.commission_rate) + self.fixed_charge
        self.balance -= entry_cost

        session = self.get_session()
        ts = timestamp if timestamp else (signal.timestamp if signal.timestamp else datetime.datetime.utcnow())
        trade = Trade(
            timestamp=ts,
            index_name=signal.index_name,
            instrument_key=signal.side, # Simplified for paper trading
            instrument_ce=signal.details.get('ce_key'),
            instrument_pe=signal.details.get('pe_key'),
            side='BUY',
            price=entry_price,
            index_price=index_price if index_price else signal.index_price,
            quantity=quantity,
            status='OPEN',
            trailing_sl=0.0
        )
        session.add(trade)
        session.commit()

        self.positions[signal.index_name] = {
            'trade_id': trade.id,
            'side': signal.side,
            'entry_price': signal.option_price,
            'quantity': quantity,
            'ce_key': signal.details.get('ce_key'),
            'pe_key': signal.details.get('pe_key'),
            'trailing_sl': 0.0
        }

        print(f"Executed BUY for {signal.index_name}: {signal.side} at {signal.option_price}")
        session.close()
        return trade

    def update_trailing_sl(self, index_name, new_sl):
        """
        Updates the trailing stop loss for an open position in the database.
        """
        if index_name not in self.positions:
            return

        pos = self.positions[index_name]
        pos['trailing_sl'] = new_sl

        def do_update():
            session = self.get_session()
            try:
                trade = session.query(Trade).filter_by(id=pos['trade_id']).first()
                if trade:
                    trade.trailing_sl = new_sl
                    session.commit()
            except Exception as e:
                print(f"Error updating trailing SL in DB: {e}")
                session.rollback()
            finally:
                session.close()

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(do_update))
        except RuntimeError:
            # No running loop, perform update synchronously
            do_update()

    def close_position(self, index_name, current_price, timestamp=None, index_price=None):
        """
        Closes an open position.
        """
        if index_name not in self.positions:
            return None

        pos = self.positions.pop(index_name)
        session = self.get_session()
        trade = session.query(Trade).filter_by(id=pos['trade_id']).first()

        # Apply slippage to exit price
        exit_price = current_price * (1 - self.slippage)
        exit_cost = (exit_price * pos['quantity'] * self.commission_rate) + self.fixed_charge

        pnl_gross = (exit_price - pos['entry_price']) * pos['quantity']
        pnl_net = pnl_gross - exit_cost

        self.balance += pnl_net

        exit_trade = Trade(
            timestamp=timestamp if timestamp else datetime.datetime.utcnow(),
            index_name=index_name,
            instrument_key=pos['side'],
            side='SELL',
            price=exit_price,
            index_price=index_price,
            quantity=pos['quantity'],
            status='CLOSED',
            pnl=pnl_net
        )

        trade.status = 'CLOSED'
        trade.pnl = exit_trade.pnl
        trade.exit_price = exit_price

        session.add(exit_trade)
        session.commit()

        print(f"Closed {index_name} position: {pos['side']} at {current_price}, PnL: {exit_trade.pnl}")
        session.close()
        return exit_trade
