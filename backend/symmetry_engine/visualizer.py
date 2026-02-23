import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from .database import get_session, Signal, Trade, ReferenceLevel

class Visualizer:
    def __init__(self, index_name):
        self.index_name = index_name

    def generate_chart(self, candles_df, output_file='chart.html'):
        """
        Generates a candlestick chart with signals and trades.
        candles_df should have timestamp, open, high, low, close.
        """
        session = get_session()
        signals = session.query(Signal).filter_by(index_name=self.index_name).all()
        trades = session.query(Trade).filter_by(index_name=self.index_name).all()
        refs = session.query(ReferenceLevel).filter_by(index_name=self.index_name).all()
        session.close()

        fig = make_subplots(rows=1, cols=1)

        # Candlestick
        fig.add_trace(go.Candlestick(
            x=candles_df['timestamp'],
            open=candles_df['open'],
            high=candles_df['high'],
            low=candles_df['low'],
            close=candles_df['close'],
            name='Index'
        ))

        # Signals
        if signals:
            sig_df = pd.DataFrame([{
                'timestamp': s.timestamp,
                'price': s.index_price,
                'side': s.side
            } for s in signals])

            buy_ce = sig_df[sig_df['side'] == 'BUY_CE']
            buy_pe = sig_df[sig_df['side'] == 'BUY_PE']

            fig.add_trace(go.Scatter(
                x=buy_ce['timestamp'],
                y=buy_ce['price'],
                mode='markers',
                marker=dict(symbol='triangle-up', size=12, color='green'),
                name='Signal BUY_CE'
            ))

            fig.add_trace(go.Scatter(
                x=buy_pe['timestamp'],
                y=buy_pe['price'],
                mode='markers',
                marker=dict(symbol='triangle-down', size=12, color='red'),
                name='Signal BUY_PE'
            ))

        # Trades (Entries and Exits)
        for t in trades:
            color = 'blue' if t.side == 'BUY' else 'orange'
            # Use index_price if available, fallback to price (option price) if not
            y_price = t.index_price if t.index_price else t.price
            fig.add_trace(go.Scatter(
                x=[t.timestamp],
                y=[y_price],
                mode='markers',
                marker=dict(symbol='circle', size=10, color=color, line=dict(width=2, color='white')),
                name=f'Trade {t.side} {t.instrument_key}',
                hoverinfo='text',
                text=f"Side: {t.side}<br>Index Price: {t.index_price}<br>Option Price: {t.price}<br>PnL: {t.pnl}"
            ))

        # Remove post-market gaps
        fig.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]), # hide weekends
                dict(bounds=[15.5, 9.25], pattern="hour"), # hide after hours (15:30 to 09:15)
            ]
        )

        fig.update_layout(title=f'{self.index_name} Symmetry Strategy Backtest', xaxis_rangeslider_visible=False)
        fig.write_html(output_file)
        print(f"Chart generated: {output_file}")
