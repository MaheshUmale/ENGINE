from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import sqlite3
import pandas as pd
import os
from .config import DB_PATH

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
        all_closed_trades = pd.read_sql("SELECT pnl FROM trades WHERE side = 'SELL' AND status = 'CLOSED'", conn)

        # Calculate summary
        total_pnl = all_closed_trades['pnl'].sum() if not all_closed_trades.empty else 0
        trade_count = len(all_closed_trades)
        win_rate = (len(all_closed_trades[all_closed_trades['pnl'] > 0]) / trade_count * 100) if trade_count > 0 else 0
        avg_pnl = all_closed_trades['pnl'].mean() if not all_closed_trades.empty else 0
    except Exception as e:
        return f"Error reading database: {e}"
    finally:
        conn.close()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "trades": trades_display.to_dict(orient="records"),
        "signals": signals.to_dict(orient="records"),
        "total_pnl": total_pnl,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl
    })

def run_dashboard():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
