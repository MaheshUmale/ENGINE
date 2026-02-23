from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
import sqlite3
import pandas as pd
import os
import json
import plotly.graph_objects as go
from .config import DB_PATH
from .database import get_session, AppSetting, Notification

app = FastAPI(title="Symmetry Engine Dashboard")
# Templates are in the root templates directory
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not os.path.exists(DB_PATH):
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "trades": [],
            "signals": [],
            "error": "Database not found. Run the bot first."
        })

    conn = sqlite3.connect(DB_PATH)
    try:
        # Fetch data for display
        trades_display = pd.read_sql("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 50", conn)
        signals = pd.read_sql("SELECT * FROM signals ORDER BY timestamp DESC LIMIT 50", conn)

        # Fetch data for summary calculations (full history of closed trades)
        all_closed_trades = pd.read_sql("SELECT pnl, timestamp FROM trades WHERE side = 'SELL' AND status = 'CLOSED' ORDER BY timestamp", conn)

        # Calculate summary
        total_pnl = all_closed_trades['pnl'].sum() if not all_closed_trades.empty else 0
        trade_count = len(all_closed_trades)
        win_rate = (len(all_closed_trades[all_closed_trades['pnl'] > 0]) / trade_count * 100) if trade_count > 0 else 0
        avg_pnl = all_closed_trades['pnl'].mean() if not all_closed_trades.empty else 0

        # Equity Curve
        equity_json = None
        max_drawdown = 0
        sharpe_ratio = 0

        if not all_closed_trades.empty:
            all_closed_trades['cum_pnl'] = all_closed_trades['pnl'].cumsum()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=all_closed_trades['timestamp'], y=all_closed_trades['cum_pnl'], mode='lines', name='Equity Curve'))
            fig.update_layout(title="Equity Curve", xaxis_title="Time", yaxis_title="Net PnL", height=400, margin=dict(l=20, r=20, t=40, b=20))
            equity_json = fig.to_json()

            # Metrics
            cum_pnl = all_closed_trades['cum_pnl']
            max_pnl = cum_pnl.expanding().max()
            drawdown = cum_pnl - max_pnl
            max_drawdown = drawdown.min()

            if len(all_closed_trades['pnl']) > 1:
                std = all_closed_trades['pnl'].std()
                sharpe_ratio = (avg_pnl / std) * (252**0.5) if std != 0 else 0

    except Exception as e:
        return f"Error reading database: {e}"
    finally:
        conn.close()

    # Fetch notifications and settings
    notifications = []
    alerts_enabled = True
    session = get_session()
    try:
        notifs = session.query(Notification).order_by(Notification.timestamp.desc()).limit(20).all()
        notifications = [{"message": n.message, "timestamp": n.timestamp} for n in notifs]

        setting = session.query(AppSetting).filter_by(key='ENABLE_ALERTS').first()
        if setting:
            alerts_enabled = setting.value == 'True'
    finally:
        session.close()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "trades": trades_display.to_dict(orient="records"),
        "signals": signals.to_dict(orient="records"),
        "notifications": notifications,
        "alerts_enabled": alerts_enabled,
        "total_pnl": total_pnl,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "equity_chart": equity_json
    })

@app.post("/toggle-alerts")
async def toggle_alerts(enabled: str = Form(...)):
    session = get_session()
    try:
        setting = session.query(AppSetting).filter_by(key='ENABLE_ALERTS').first()
        if not setting:
            setting = AppSetting(key='ENABLE_ALERTS', value=enabled)
            session.add(setting)
        else:
            setting.value = enabled
        session.commit()
    finally:
        session.close()
    return RedirectResponse(url="/", status_code=303)

def run_dashboard():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
