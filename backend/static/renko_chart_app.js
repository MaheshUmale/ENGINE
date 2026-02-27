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
        this.accVolume = 0;
    }

    setBoxSize(bs) {
        this.boxSize = bs;
        this.reset();
    }

    processTick(tick) {
        // Handle both DB format (price) and live feed format (last_price)
        const price = Number(tick.price || tick.last_price);
        const volume = Number(tick.qty || tick.ltq || 0);
        let ts = Math.floor(tick.ts_ms / 1000);

        if (isNaN(price) || price <= 0) return [];

        if (this.lastRenkoClose === 0) {
            this.lastRenkoClose = price;
            this.lastTime = ts;
            this.accVolume = volume;
            return [];
        }

        this.accVolume += volume;
        const bars = [];
        let diff = price - this.lastRenkoClose;

        while (Math.abs(diff) >= this.boxSize) {
            // Ensure each renko bar has a unique timestamp for the chart
            if (ts <= this.lastTime) ts = this.lastTime + 1;
            this.lastTime = ts;

            const open = this.lastRenkoClose;
            const close = diff > 0 ? open + this.boxSize : open - this.boxSize;

            bars.push({
                time: ts,
                open,
                high: Math.max(open, close),
                low: Math.min(open, close),
                close,
                volume: this.accVolume // Assign accumulated volume to the bar
            });

            this.lastRenkoClose = close;
            diff = price - this.lastRenkoClose;
            this.accVolume = 0; // Reset for next bar
        }
        return bars;
    }
}

class RenkoChartManager {
    constructor() {
        this.socket = io({ reconnectionAttempts: 5, timeout: 10000 });
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

        // Add Volume Series
        this.volumeSeries = this.chart.addHistogramSeries({
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
            lastValueVisible: false,
            priceLineVisible: false
        });

        this.chart.priceScale('volume').applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
            visible: false
        });

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
        const volumes = [];

        ticks.forEach(t => {
            this.aggregator.processTick(t).forEach(b => {
                candles.push({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
                volumes.push({
                    time: b.time,
                    value: b.volume,
                    color: b.close >= b.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)'
                });
            });
        });

        this.series.setData(candles);
        this.volumeSeries.setData(volumes);

        if (candles.length) {
            document.getElementById('last-price').textContent = candles[candles.length-1].close.toLocaleString();
        }
    }

    setupSocket() {
        this.socket.on('connect', () => {
            console.log("[Renko] Connected, subscribing to:", this.symbol);
            this.socket.emit('subscribe', { instrumentKeys: [this.symbol] });
            this.updateStatus('LIVE', '#22c55e');
        });

        this.socket.on('disconnect', () => {
            this.updateStatus('DISCONNECTED', '#ef4444');
        });

        this.socket.on('connect_error', () => {
            this.updateStatus('ERROR', '#f59e0b');
        });

        this.socket.on('raw_tick', (data) => {
            // Data can contain the symbol key, or the HRN, or canonical key
            // Search through keys for our symbol
            let tick = null;
            for (const key of Object.keys(data)) {
                if (key.toUpperCase() === this.symbol.toUpperCase()) {
                    tick = data[key];
                    break;
                }
            }

            if (tick) {
                const bars = this.aggregator.processTick(tick);
                bars.forEach(b => {
                    this.series.update({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
                    this.volumeSeries.update({
                        time: b.time,
                        value: b.volume,
                        color: b.close >= b.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)'
                    });
                });

                if (bars.length) {
                    const lastBar = bars[bars.length-1];
                    document.getElementById('last-price').textContent = lastBar.close.toLocaleString();
                }
            }
        });
    }

    updateStatus(text, color) {
        const dot = document.getElementById('status-dot');
        const label = document.getElementById('status-text');
        if (dot) dot.style.backgroundColor = color;
        if (label) {
            label.textContent = text;
            label.style.color = color;
        }
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
