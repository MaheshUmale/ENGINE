/**
 * PRODESK Advanced Order Flow Terminal v3.0
 * High-performance Volume Footprint and Delta Analytics Engine.
 */

class OrderFlowEngine {
    /**
     * @param {number} tpc Ticks per candle
     * @param {number} priceStep Minimum price movement (tick size)
     */
    constructor(tpc = 100, priceStep = 0.05) {
        this.tpc = tpc;
        this.priceStep = priceStep;
        this.reset();
    }

    reset() {
        this.ticks = [];
        this.candles = [];
        this.currentCandle = null;
        this.tickCount = 0;
        this.cvd = 0;
        this.lastPrice = 0;
        this.lastSide = 1; // 1: Buy, -1: Sell
    }

    setParams(tpc, priceStep) {
        this.tpc = tpc || this.tpc;
        this.priceStep = priceStep || this.priceStep;
    }

    /**
     * Aggregates raw ticks into Order Flow candles with footprints.
     */
    processTick(tick, isReaggregating = false) {
        const rawPrice = Number(tick.price);
        if (isNaN(rawPrice) || rawPrice <= 0) return null;

        const price = Number((Math.round(rawPrice / this.priceStep) * this.priceStep).toFixed(2));
        const qty = Number(tick.qty || 0);
        let ts = Math.floor(tick.ts_ms / 1000);

        if (isNaN(ts) || ts <= 0) ts = Math.floor(Date.now() / 1000);

        // Determine Aggressor Side using Tick Rule
        let side = this.lastSide;
        if (price > this.lastPrice) side = 1;
        else if (price < this.lastPrice) side = -1;

        const delta = side * qty;
        this.cvd += delta;
        this.lastPrice = price;
        this.lastSide = side;

        if (!isReaggregating) {
            this.ticks.push({ ts_ms: tick.ts_ms, price: rawPrice, qty: qty });
            if (this.ticks.length > 30000) this.ticks.shift();
        }

        if (!this.currentCandle || this.tickCount >= this.tpc) {
            if (this.currentCandle) this.calculateAnalytics(this.currentCandle);

            // Time continuity check
            if (this.currentCandle && ts <= this.currentCandle.time) ts = this.currentCandle.time + 1;

            this.currentCandle = {
                time: ts,
                open: price, high: price, low: price, close: price,
                volume: qty, delta: delta, cvd: this.cvd,
                cvdOpen: this.cvd - delta, cvdHigh: Math.max(this.cvd - delta, this.cvd),
                cvdLow: Math.min(this.cvd - delta, this.cvd), cvdClose: this.cvd,
                footprint: {}, imbalances: [],
                poc: price, vah: price, val: price
            };
            this.updateFootprint(this.currentCandle, price, side, qty);
            this.tickCount = 1;
            this.candles.push(this.currentCandle);
            if (this.candles.length > 2000) this.candles.shift();
            return { type: 'new', candle: this.currentCandle };
        } else {
            const c = this.currentCandle;
            c.high = Math.max(c.high, price);
            c.low = Math.min(c.low, price);
            c.close = price;
            c.volume += qty;
            c.delta += delta;
            c.cvd = this.cvd;
            c.cvdClose = this.cvd;
            c.cvdHigh = Math.max(c.cvdHigh, this.cvd);
            c.cvdLow = Math.min(c.cvdLow, this.cvd);
            this.updateFootprint(c, price, side, qty);
            this.tickCount++;
            return { type: 'update', candle: this.currentCandle };
        }
    }

    updateFootprint(candle, price, side, qty) {
        if (!candle.footprint[price]) candle.footprint[price] = { buy: 0, sell: 0 };
        if (side === 1) candle.footprint[price].buy += qty;
        else candle.footprint[price].sell += qty;

        const now = Date.now();
        if (!candle._lastCalc || now - candle._lastCalc > 300) {
            this.calculateAnalytics(candle);
            candle._lastCalc = now;
        }
    }

    /**
     * Calculates Volume Profile (POC, VA) and Diagonal Imbalances (3:1).
     */
    calculateAnalytics(candle) {
        const fp = candle.footprint;
        const prices = Object.keys(fp).map(Number).sort((a, b) => a - b);
        if (prices.length === 0) return;

        let totalVol = 0, maxVol = 0, poc = prices[0];
        for (const p of prices) {
            const vol = fp[p].buy + fp[p].sell;
            totalVol += vol;
            if (vol > maxVol) { maxVol = vol; poc = p; }
        }
        candle.poc = poc;

        // Value Area (70% Volume)
        const targetVaVol = totalVol * 0.7;
        let currentVaVol = maxVol;
        let lIdx = prices.indexOf(poc), uIdx = lIdx;

        while (currentVaVol < targetVaVol && (lIdx > 0 || uIdx < prices.length - 1)) {
            const lVol = lIdx > 0 ? (fp[prices[lIdx - 1]].buy + fp[prices[lIdx - 1]].sell) : 0;
            const uVol = uIdx < prices.length - 1 ? (fp[prices[uIdx + 1]].buy + fp[prices[uIdx + 1]].sell) : 0;
            if (lIdx > 0 && (lVol >= uVol || uIdx === prices.length - 1)) { currentVaVol += lVol; lIdx--; }
            else if (uIdx < prices.length - 1) { currentVaVol += uVol; uIdx++; }
            else break;
        }
        candle.vah = prices[uIdx];
        candle.val = prices[lIdx];

        // Diagonal Imbalances (300% ratio)
        candle.imbalances = [];
        for (let i = 0; i < prices.length; i++) {
            const p = prices[i];
            if (i > 0 && fp[p].buy >= fp[prices[i-1]].sell * 3 && fp[p].buy > 0) candle.imbalances.push({ price: p, side: 'buy' });
            if (i < prices.length - 1 && fp[p].sell >= fp[prices[i+1]].buy * 3 && fp[p].sell > 0) candle.imbalances.push({ price: p, side: 'sell' });
        }
    }
}

class CanvasRenderer {
    constructor(canvas, chart, series) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.chart = chart;
        this.series = series;
        this.colors = { bull: '#00ffc2', bear: '#ff3366', poc: '#fbbf24', va: 'rgba(255, 255, 255, 0.08)' };
        this.updateTheme();
    }

    updateTheme() {
        const isLight = document.body.classList.contains('light-theme');
        this.colors.va = isLight ? 'rgba(15, 23, 42, 0.08)' : 'rgba(255, 255, 255, 0.08)';
        this.colors.text = isLight ? '#475569' : '#9ea7b3';
    }

    render(candles) {
        if (!this.ctx || !this.chart || !candles.length) return;
        const timeScale = this.chart.timeScale();
        const spacing = timeScale.options().barSpacing;

        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        if (spacing < 40) return; // Hide footprints when zoomed out

        // Use binary search for visible range for O(log N) performance
        const visibleRange = timeScale.getVisibleLogicalRange();
        if (!visibleRange) return;

        candles.forEach(c => {
            const x = timeScale.timeToCoordinate(c.time);
            if (x !== null && x > -spacing && x < this.canvas.width + spacing) {
                this.drawFootprint(c, x, spacing);
            }
        });
    }

    drawFootprint(candle, x, spacing) {
        const fp = candle.footprint;
        const prices = Object.keys(fp).map(Number).sort((a, b) => b - a);
        const halfWidth = spacing / 2;

        // Draw Value Area Box
        if (candle.vah && candle.val) {
            const y1 = this.series.priceToCoordinate(candle.vah), y2 = this.series.priceToCoordinate(candle.val);
            this.ctx.fillStyle = this.colors.va;
            this.ctx.fillRect(x - halfWidth, y1 - 4, spacing, y2 - y1 + 8);
        }

        this.ctx.font = 'bold 9px "IBM Plex Mono"';
        prices.forEach(p => {
            const y = this.series.priceToCoordinate(p);
            if (y === null || y < 0 || y > this.canvas.height) return;

            const { buy, sell } = fp[p];
            const isPoc = p === candle.poc;

            if (isPoc) {
                this.ctx.fillStyle = 'rgba(251, 191, 36, 0.2)';
                this.ctx.fillRect(x - halfWidth, y - 5, spacing, 10);
            }

            const formatV = (v) => {
                if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M';
                if (v >= 1000) return (v / 1000).toFixed(1) + 'K';
                return v;
            };

            this.ctx.textAlign = 'right';
            this.ctx.fillStyle = sell > buy ? '#ff3366' : this.colors.text;
            this.ctx.fillText(formatV(sell), x - 4, y + 3);

            this.ctx.textAlign = 'left';
            this.ctx.fillStyle = buy > sell ? '#00ffc2' : this.colors.text;
            this.ctx.fillText(formatV(buy), x + 4, y + 3);
        });
    }
}

class OrderFlowUI {
    constructor() {
        this.engine = new OrderFlowEngine();
        this.charts = {};
        this.socket = io();

        // Parse URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        this.symbol = urlParams.get('symbol')?.toUpperCase() || 'NSE:NIFTY';
        const tpc = parseInt(urlParams.get('ticks')) || 100;
        const priceStep = parseFloat(urlParams.get('step')) || 1.0;

        this.engine.setParams(tpc, priceStep);
        this.markers = [];
        this.init();
    }

    init() {
        this.loadTheme();
        this.setupCharts();
        this.setupSocket();
        this.setupListeners();
        this.loadHistory();

        window.addEventListener('resize', () => this.handleResize());
        setTimeout(() => this.handleResize(), 100);
    }

    loadTheme() {
        const theme = localStorage.getItem('theme') || 'dark';
        document.body.classList.toggle('light-theme', theme === 'light');
        this.applyThemeIcons();
    }

    applyThemeIcons() {
        const isLight = document.body.classList.contains('light-theme');
        document.getElementById('sunIcon')?.classList.toggle('hidden', !isLight);
        document.getElementById('moonIcon')?.classList.toggle('hidden', isLight);
    }

    toggleTheme() {
        const isLight = document.body.classList.toggle('light-theme');
        localStorage.setItem('theme', isLight ? 'light' : 'dark');
        this.applyThemeIcons();
        this.updateChartTheme();
    }

    updateChartTheme() {
        const isLight = document.body.classList.contains('light-theme');
        const options = {
            layout: { textColor: isLight ? '#1e293b' : '#7d8590' },
            grid: {
                vertLines: { color: isLight ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.02)' },
                horzLines: { color: isLight ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.02)' }
            },
            timeScale: { borderColor: isLight ? 'rgba(0,0,0,0.1)' : 'rgba(255,255,255,0.1)' },
            rightPriceScale: { borderColor: isLight ? 'rgba(0,0,0,0.1)' : 'rgba(255,255,255,0.1)' }
        };

        this.charts.main.applyOptions(options);
        this.charts.cvd.applyOptions(options);
        this.renderer.updateTheme();
        this.renderer.render(this.engine.candles);
    }

    setupCharts() {
        const options = {
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#7d8590' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.02)' }, horzLines: { color: 'rgba(255,255,255,0.02)' } },
            timeScale: {
                rightOffset: 15,
                timeVisible: true,
                secondsVisible: true,
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
            },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' }
        };

        this.charts.main = LightweightCharts.createChart(document.getElementById('main-chart'), options);
        this.charts.candles = this.charts.main.addCandlestickSeries({
            upColor: 'rgba(0, 255, 195, 0.2)', downColor: 'rgba(255, 51, 102, 0.2)',
            borderVisible: false, wickVisible: true
        });

        this.charts.cvd = LightweightCharts.createChart(document.getElementById('cvd-chart'), { ...options, timeScale: { visible: false } });
        this.charts.cvdSeries = this.charts.cvd.addCandlestickSeries({ upColor: '#00ffc2', downColor: '#ff3366', borderVisible: false });

        this.charts.main.timeScale().subscribeVisibleLogicalRangeChange(range => {
            this.charts.cvd.timeScale().setVisibleLogicalRange(range);
            this.renderer.render(this.engine.candles);
        });

        this.renderer = new CanvasRenderer(document.getElementById('footprint-canvas'), this.charts.main, this.charts.candles);
    }

    setupSocket() {
        this.socket.on('connect', () => {
            this.socket.emit('subscribe', { instrumentKeys: [this.symbol] });
            this.updateStatus('Live', 'bg-[#00ffc2]');
        });

        this.socket.on('raw_tick', (data) => {
            const tick = data[this.symbol];
            if (!tick?.last_price) return;
            const res = this.engine.processTick({ price: tick.last_price, qty: tick.ltq || 1, ts_ms: tick.ts_ms || Date.now() });
            if (res) this.updateChartData(res.candle);
        });
    }

    updateChartData(candle) {
        this.charts.candles.update(candle);
        this.charts.cvdSeries.update({
            time: candle.time, open: candle.cvdOpen, high: candle.cvdHigh, low: candle.cvdLow, close: candle.cvdClose
        });
        requestAnimationFrame(() => this.renderer.render(this.engine.candles));
        this.updateUI(candle);
    }

    async loadHistory() {
        this.updateStatus('Loading...', 'bg-yellow-500');
        try {
            const res = await fetch(`/api/ticks/history/${encodeURIComponent(this.symbol)}?limit=15000`).then(r => r.json());
            this.engine.reset();
            (res.history || []).forEach(t => this.engine.processTick(t, false));

            this.charts.candles.setData(this.engine.candles);
            this.charts.cvdSeries.setData(this.engine.candles.map(c => ({
                time: c.time, open: c.cvdOpen, high: c.cvdHigh, low: c.cvdLow, close: c.cvdClose
            })));

            this.charts.main.timeScale().fitContent();
            this.renderer.render(this.engine.candles);
            this.updateStatus('Live', 'bg-[#00ffc2]');
        } catch (e) { this.updateStatus('Error', 'bg-red-500'); }
    }

    setupListeners() {
        // Sync inputs with engine state
        const ticksInput = document.getElementById('ticks-input');
        const stepInput = document.getElementById('step-input');
        const displaySymbol = document.getElementById('display-symbol');

        if (ticksInput) ticksInput.value = this.engine.tpc;
        if (stepInput) stepInput.value = this.engine.priceStep.toFixed(2);
        if (displaySymbol) displaySymbol.textContent = this.symbol;

        ticksInput.addEventListener('change', (e) => {
            this.engine.tpc = parseInt(e.target.value) || 100;
            this.reaggregate();
        });
        stepInput.addEventListener('change', (e) => {
            this.engine.priceStep = parseFloat(e.target.value) || 0.50;
            this.reaggregate();
        });

        document.getElementById('zoomInBtn')?.addEventListener('click', () => {
            const ts = this.charts.main.timeScale();
            ts.applyOptions({ barSpacing: Math.min(100, ts.options().barSpacing * 1.2) });
        });
        document.getElementById('zoomOutBtn')?.addEventListener('click', () => {
            const ts = this.charts.main.timeScale();
            ts.applyOptions({ barSpacing: Math.max(1, ts.options().barSpacing / 1.2) });
        });
        document.getElementById('resetZoomBtn')?.addEventListener('click', () => {
            this.charts.main.timeScale().fitContent();
        });

        document.getElementById('replay-btn')?.addEventListener('click', () => {
            this.startReplay();
        });

        document.getElementById('themeToggleBtn')?.addEventListener('click', () => {
            this.toggleTheme();
        });
    }

    startReplay() {
        const ticks = [...this.engine.ticks];
        if (ticks.length < 10) { alert("Insufficient data for replay"); return; }

        this.engine.reset();
        this.charts.candles.setData([]);
        this.charts.cvdSeries.setData([]);

        let i = 0;
        const interval = setInterval(() => {
            if (i >= ticks.length) {
                clearInterval(interval);
                this.updateStatus('Live', 'bg-[#00ffc2]');
                return;
            }
            const res = this.engine.processTick(ticks[i], true);
            if (res) this.updateChartData(res.candle);
            i++;
            this.updateStatus(`Replay ${Math.floor(i/ticks.length*100)}%`, 'bg-blue-500');
        }, 10);
    }

    reaggregate() {
        document.getElementById('reaggregate-overlay').classList.remove('hidden');
        setTimeout(() => {
            const ticks = [...this.engine.ticks];
            this.engine.reset();
            ticks.forEach(t => this.engine.processTick(t, true));
            this.engine.ticks = ticks;

            this.charts.candles.setData(this.engine.candles);
            this.charts.cvdSeries.setData(this.engine.candles.map(c => ({
                time: c.time, open: c.cvdOpen, high: c.cvdHigh, low: c.cvdLow, close: c.cvdClose
            })));
            this.charts.main.timeScale().fitContent();
            this.renderer.render(this.engine.candles);
            document.getElementById('reaggregate-overlay').classList.add('hidden');
        }, 50);
    }

    updateStatus(text, color) {
        document.getElementById('status-text').textContent = text;
        document.getElementById('status-dot').className = `w-1.5 h-1.5 rounded-full ${color}`;
    }

    updateUI(candle) {
        document.getElementById('last-price').textContent = candle.close.toFixed(2);
        document.getElementById('delta-summary').textContent = `DELTA: ${Math.round(candle.delta)} | CVD: ${Math.round(candle.cvd)}`;
    }

    handleResize() {
        const w = document.getElementById('chart-wrapper');
        const cvd = document.getElementById('cvd-chart');
        const canvas = document.getElementById('footprint-canvas');
        if (!w || !cvd) return;

        this.charts.main.resize(w.clientWidth, w.clientHeight);
        this.charts.cvd.resize(cvd.clientWidth, cvd.clientHeight);
        canvas.width = w.clientWidth;
        canvas.height = w.clientHeight;
        this.renderer.render(this.engine.candles);
    }
}

// Bootstrap
document.addEventListener('DOMContentLoaded', () => {
    window.orderflowUI = new OrderFlowUI();
});
