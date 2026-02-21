from .database import get_session, Trade
import datetime

class ExecutionEngine:
    def __init__(self, initial_balance=1000000, slippage=0.001, commission_rate=0.0005, fixed_charge=20):
        self.balance = initial_balance
        self.slippage = slippage # 0.1% default
        self.commission_rate = commission_rate # 0.05%
        self.fixed_charge = fixed_charge # Flat INR 20 per trade
        self.positions = {} # index_name -> position

    def execute_signal(self, signal, timestamp=None, index_price=None):
        """
        Executes a signal by entering a paper trade.
        """
        if signal.index_name in self.positions:
            return None # Already in a position for this index

        # Apply slippage to entry price
        entry_price = signal.option_price * (1 + self.slippage)
        # Turnover-based commission + fixed charge
        entry_cost = (entry_price * 100 * self.commission_rate) + self.fixed_charge
        self.balance -= entry_cost

        session = get_session()
        trade = Trade(
            timestamp=timestamp if timestamp else signal.timestamp,
            index_name=signal.index_name,
            instrument_key=signal.side, # Simplified for paper trading
            side='BUY',
            price=entry_price,
            index_price=index_price if index_price else signal.index_price,
            quantity=100, # Fixed quantity for now
            status='OPEN'
        )
        session.add(trade)
        session.commit()

        self.positions[signal.index_name] = {
            'trade_id': trade.id,
            'side': signal.side,
            'entry_price': signal.option_price,
            'quantity': 100,
            'ce_key': signal.details.get('ce_key'),
            'pe_key': signal.details.get('pe_key')
        }

        print(f"Executed BUY for {signal.index_name}: {signal.side} at {signal.option_price}")
        session.close()
        return trade

    def close_position(self, index_name, current_price, timestamp=None, index_price=None):
        """
        Closes an open position.
        """
        if index_name not in self.positions:
            return None

        pos = self.positions.pop(index_name)
        session = get_session()
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

        session.add(exit_trade)
        session.commit()

        print(f"Closed {index_name} position: {pos['side']} at {current_price}, PnL: {exit_trade.pnl}")
        session.close()
        return exit_trade
