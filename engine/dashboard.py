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
        trades = pd.read_sql("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 50", conn)
        signals = pd.read_sql("SELECT * FROM signals ORDER BY timestamp DESC LIMIT 50", conn)

        # Calculate summary
        closed_trades = trades[trades['side'] == 'SELL']
        total_pnl = closed_trades['pnl'].sum() if not closed_trades.empty else 0
        trade_count = len(closed_trades)
        win_rate = (len(closed_trades[closed_trades['pnl'] > 0]) / trade_count * 100) if trade_count > 0 else 0
        avg_pnl = closed_trades['pnl'].mean() if not closed_trades.empty else 0
    except Exception as e:
        return f"Error reading database: {e}"
    finally:
        conn.close()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "trades": trades.to_dict(orient="records"),
        "signals": signals.to_dict(orient="records"),
        "total_pnl": total_pnl,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl
    })

def run_dashboard():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
