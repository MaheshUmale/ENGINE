/**
 * PRODESK Renko Chart Engine v3.0
 */

class RenkoAggregator {
    constructor(boxSize) {
        this.boxSize = boxSize;
        this.reset();
    }

    reset() {
        this.lastRenkoClose = 0;
        this.lastTime = 0;
    }

    setBoxSize(bs) {
        this.boxSize = bs;
        this.reset();
    }

    processTick(tick) {
        const price = Number(tick.price);
        let ts = Math.floor(tick.ts_ms / 1000);
        if (this.lastRenkoClose === 0) { this.lastRenkoClose = price; this.lastTime = ts; return []; }

        const bars = [];
        let diff = price - this.lastRenkoClose;
        while (Math.abs(diff) >= this.boxSize) {
            if (ts <= this.lastTime) ts = this.lastTime + 1;
            this.lastTime = ts;
            const open = this.lastRenkoClose;
            const close = diff > 0 ? open + this.boxSize : open - this.boxSize;
            bars.push({ time: ts, open, high: Math.max(open, close), low: Math.min(open, close), close });
            this.lastRenkoClose = close;
            diff = price - this.lastRenkoClose;
        }
        return bars;
    }
}

class RenkoChartManager {
    constructor() {
        this.socket = io();
        this.symbol = new URLSearchParams(window.location.search).get('symbol')?.toUpperCase() || 'NSE:NIFTY';
        this.aggregator = new RenkoAggregator(parseFloat(new URLSearchParams(window.location.search).get('boxSize')) || 10);
        this.historicalTicks = [];
        this.init();
    }

    init() {
        this.setupChart();
        this.setupSocket();
        this.setupListeners();
        this.loadHistory();
        document.getElementById('display-symbol').textContent = this.symbol;
    }

    setupChart() {
        const isL = document.body.classList.contains('light-theme');
        this.chart = LightweightCharts.createChart(document.getElementById('chart'), {
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: isL ? '#1e293b' : '#f8fafc' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
            timeScale: {
                timeVisible: true,
                borderColor: 'rgba(255,255,255,0.1)',
                tickMarkFormatter: (time, tickMarkType, locale) => {
                    const date = new Date(time * 1000);
                    return date.toLocaleTimeString('en-IN', {
                        timeZone: 'Asia/Kolkata',
                        hour: '2-digit',
                        minute: '2-digit',
                        hour12: false
                    });
                }
            },
            localization: {
                timeFormatter: (time) => {
                    const date = new Date(time * 1000);
                    return date.toLocaleTimeString('en-IN', {
                        timeZone: 'Asia/Kolkata',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                        hour12: false
                    });
                }
            }
        });
        this.series = this.chart.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444' });
        window.addEventListener('resize', () => this.chart.resize(document.getElementById('chart').clientWidth, document.getElementById('chart').clientHeight));
    }

    async loadHistory() {
        const res = await fetch(`/api/ticks/history/${encodeURIComponent(this.symbol)}?limit=10000`).then(r => r.json());
        this.historicalTicks = res.history || [];
        this.renderTicks(this.historicalTicks);
    }

    renderTicks(ticks) {
        this.aggregator.reset();
        const candles = [];
        ticks.forEach(t => this.aggregator.processTick(t).forEach(b => candles.push(b)));
        this.series.setData(candles);
        if (candles.length) document.getElementById('last-price').textContent = candles[candles.length-1].close.toLocaleString();
    }

    setupSocket() {
        this.socket.on('connect', () => this.socket.emit('subscribe', { instrumentKeys: [this.symbol] }));
        this.socket.on('raw_tick', (data) => {
            if (data[this.symbol]) {
                const bars = this.aggregator.processTick(data[this.symbol]);
                bars.forEach(b => this.series.update(b));
                if (bars.length) document.getElementById('last-price').textContent = bars[bars.length-1].close.toLocaleString();
            }
        });
    }

    setupListeners() {
        document.getElementById('box-size-input').addEventListener('change', (e) => {
            this.aggregator.setBoxSize(parseFloat(e.target.value) || 10);
            this.renderTicks(this.historicalTicks);
        });
        document.getElementById('replay-mode-btn')?.addEventListener('click', () => {
            this.startReplay();
        });
        document.getElementById('theme-toggle').addEventListener('click', () => {
            const isL = document.body.classList.toggle('light-theme');
            this.chart.applyOptions({ layout: { textColor: isL ? '#1e293b' : '#f8fafc' } });
        });
    }

    startReplay() {
        if (this.historicalTicks.length < 10) return;
        this.aggregator.reset();
        this.series.setData([]);
        let i = 0;
        const interval = setInterval(() => {
            if (i >= this.historicalTicks.length) { clearInterval(interval); return; }
            const bars = this.aggregator.processTick(this.historicalTicks[i]);
            bars.forEach(b => this.series.update(b));
            i++;
        }, 10);
    }
}

document.addEventListener('DOMContentLoaded', () => { window.renkoChart = new RenkoChartManager(); });
