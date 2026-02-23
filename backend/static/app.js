/**
 * PRODESK Multi-Chart Engine v3.0
 * High-performance coordination of multiple TradingView Lightweight Charts.
 */

/**
 * @typedef {Object} ChartConfig
 * @property {string} symbol
 * @property {string} interval
 * @property {boolean} showIndicators
 * @property {string[]} hiddenPlots
 * @property {Object} colorOverrides
 * @property {string} chartType
 * @property {Array} drawings
 */

class DataManager {
    constructor(engine) {
        this.engine = engine;
        this.socket = io({ reconnectionAttempts: 5, timeout: 10000 });
        this.setupSocket();
    }

    setupSocket() {
        this.socket.on('connect', () => {
            console.log("[DataManager] Socket connected");
            this.engine.charts.forEach(c => this.subscribe(c.symbol, c.interval));
        });

        this.socket.on('raw_tick', (data) => {
            for (const [key, quote] of Object.entries(data)) {
                this.engine.charts.forEach(c => {
                    if (c.symbol.toUpperCase() === key.toUpperCase()) {
                        c.updateRealtimeCandle(quote);
                    }
                });
            }
        });

        this.socket.on('chart_update', (data) => {
            const key = (data.instrumentKey || "").toUpperCase();
            const interval = String(data.interval || "");
            this.engine.charts.forEach(c => {
                if (c.symbol.toUpperCase() === key && String(c.interval) === interval) {
                    c.handleChartUpdate(data);
                }
            });
        });
    }

    subscribe(symbol, interval) {
        this.socket.emit('subscribe', { instrumentKeys: [symbol], interval });
    }

    unsubscribe(symbol, interval) {
        this.socket.emit('unsubscribe', { instrumentKeys: [symbol], interval });
    }

    async fetchOIProfile(symbol) {
        try {
            const res = await fetch(`/api/options/chain/${encodeURIComponent(symbol)}/with-greeks`);
            return await res.json();
        } catch (e) {
            console.error("[DataManager] OI fetch failed:", e);
            return null;
        }
    }

    async fetchHistory(symbol, interval) {
        try {
            const settings = JSON.parse(localStorage.getItem('pro_analysis_settings') || '{}');
            const params = new URLSearchParams({ interval, ...settings });
            const res = await fetch(`/api/tv/intraday/${encodeURIComponent(symbol)}?${params.toString()}`);
            const data = await res.json();
            if (data && data.candles) {
                // API returns [ts, o, h, l, c, v] in descending or ascending order?
                // backend/api_server.py: data.candles.map(...).reverse() - wait, no.
                // In my refactored backend: sorted(tv_candles, key=lambda x: x[0])
                // So it's already sorted.
                return {
                    hrn: data.hrn || '',
                    candles: data.candles.map(c => ({
                        time: Number(c[0]), open: c[1], high: c[2], low: c[3], close: c[4], volume: c[5], rvol: c[6] || 1.0
                    })),
                    indicators: data.indicators || []
                };
            }
        } catch (e) {
            console.error("[DataManager] Fetch failed:", e);
        }
        return { candles: [], indicators: [] };
    }
}

class ChartInstance {
    constructor(id, index, engine) {
        this.id = id;
        this.index = index;
        this.engine = engine;
        this.container = document.getElementById(id);

        // State
        this.symbol = 'NSE:NIFTY';
        this.interval = '1';
        this.chartType = 'candles';
        this.hiddenPlots = new Set();
        this.colorOverrides = {};
        this.fullHistory = { candles: new Map(), volume: new Map(), indicators: {} };
        this.markers = [];
        this.drawings = [];
        this.lastCandle = null;
        this.showOIProfile = false;
        this.showIndicators = true; // Enabled by default
        this.oiLines = [];
        this.activeSymmetrySignal = null;

        this.initChart();
    }

    initChart() {
        const isLight = document.body.classList.contains('light-theme');
        this.createLegend();
        this.chart = LightweightCharts.createChart(this.container, {
            layout: {
                background: { type: 'solid', color: isLight ? '#f8fafc' : '#0f172a' },
                textColor: isLight ? '#1e293b' : '#d1d5db'
            },
            grid: {
                vertLines: { color: isLight ? '#f1f5f9' : 'rgba(255,255,255,0.05)' },
                horzLines: { color: isLight ? '#f1f5f9' : 'rgba(255,255,255,0.05)' }
            },
            timeScale: {
                rightOffset: 20,
                timeVisible: true,
                secondsVisible: false,
                borderColor: isLight ? '#e2e8f0' : 'rgba(255,255,255,0.1)',
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
            rightPriceScale: { borderColor: isLight ? '#e2e8f0' : 'rgba(255,255,255,0.1)' },
            crosshair: { mode: 0 }
        });

        this.setChartType(this.chartType);
        this.volumeSeries = this.chart.addHistogramSeries({
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
            lastValueVisible: false,
            priceLineVisible: false
        });
        this.chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 }, visible: false });

        this.container.addEventListener('mousedown', () => this.engine.setActiveChart(this.index));
        this.addLocalControls();

        // Horizontal line drawing support (Shift+Click)
        this.chart.subscribeClick((param) => {
            if (this.engine.replay.isActive && this.engine.activeIdx === this.index && param.time) {
                this.engine.replay.setStartPoint(param.time);
                return;
            }
            if (param.time && param.point) {
                const hBtn = document.getElementById('drawingToolBtn');
                const isHlineActive = hBtn && hBtn.classList.contains('bg-blue-600');
                if (isHlineActive || (param.sourceEvent && param.sourceEvent.shiftKey)) {
                    const price = this.mainSeries.coordinateToPrice(param.point.y);
                    if (price) this.addHorizontalLine(price);
                }
            }
        });
    }

    setChartType(type) {
        this.chartType = type;
        const data = Array.from(this.fullHistory.candles.values()).sort((a,b) => Number(a.time) - Number(b.time));
        if (this.mainSeries) this.chart.removeSeries(this.mainSeries);

        const options = { lastValueVisible: false, priceLineVisible: false };
        if (type === 'candles') this.mainSeries = this.chart.addCandlestickSeries({ ...options, upColor: '#22c55e', downColor: '#ef4444' });
        else if (type === 'bars') this.mainSeries = this.chart.addBarSeries({ ...options, upColor: '#22c55e', downColor: '#ef4444' });
        else if (type === 'area') this.mainSeries = this.chart.addAreaSeries({ ...options, lineColor: '#3b82f6', topColor: 'rgba(59, 130, 246, 0.4)', bottomColor: 'transparent' });
        else this.mainSeries = this.chart.addLineSeries({ ...options, color: '#3b82f6' });

        if (data.length > 0) this.mainSeries.setData(data);
        this.applyMarkers();
    }

    async switchSymbol(symbol, interval) {
        if (this.symbol && this.interval) {
            this.engine.dataManager.unsubscribe(this.symbol, this.interval);
        }

        this.symbol = symbol.toUpperCase();
        this.interval = interval || this.interval;
        this.fullHistory = { candles: new Map(), volume: new Map(), indicators: {} };
        this.markers = [];
        this.indicatorSeries = this.indicatorSeries || {};
        Object.values(this.indicatorSeries).forEach(s => this.chart.removeSeries(s));
        this.indicatorSeries = {};

        this.engine.setLoading(true);
        const data = await this.engine.dataManager.fetchHistory(this.symbol, this.interval);
        this.engine.setLoading(false);

        if (data.candles.length > 0) {
            data.candles.forEach(c => {
                const ts = Number(c.time);
                this.fullHistory.candles.set(ts, { ...c, time: ts });
            });
            this.lastCandle = data.candles[data.candles.length - 1];
            this.renderData();
            this.chart.timeScale().fitContent();
        }

        if (data.indicators) {
            this.fullHistory.indicators_raw = data.indicators;
            this.applyIndicators(data.indicators);
            this.updateLegend(data.indicators);
        }
        if (this.showOIProfile) this.toggleOIProfile(true);

        this.engine.dataManager.subscribe(this.symbol, this.interval);
        this.engine.updateUI();
    }

    getColorByRvol(candle) {
        const isUp = candle.close >= candle.open;
        const rvol = candle.rvol || 1.0;
        let baseColor = isUp ? '#22c55e' : '#ef4444';

        if (rvol >= 3) return isUp ? '#007504' : '#890101';
        if (rvol >= 2) return isUp ? '#03b309' : '#d30101';

        let alpha = "FF";
        if (rvol >= 1.6) alpha = "E6";
        else if (rvol >= 1.2) alpha = "B3";
        else if (rvol >= 0.8) alpha = "66";
        else if (rvol >= 0.5) alpha = "33";
        else alpha = "1A";

        return baseColor + alpha;
    }

    renderData() {
        const candles = Array.from(this.fullHistory.candles.values()).sort((a,b) => Number(a.time) - Number(b.time));

        const coloredCandles = candles.map(c => ({
            ...c,
            time: Number(c.time),
            color: this.getColorByRvol(c),
            borderColor: this.getColorByRvol(c),
            wickColor: this.getColorByRvol(c)
        }));
        this.mainSeries.setData(coloredCandles);

        const volumes = candles.map(c => ({
            time: c.time, value: c.volume,
            color: c.close >= c.open ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)'
        }));
        this.volumeSeries.setData(volumes);
    }

    updateRealtimeCandle(quote) {
        // Block live updates during Replay for the active chart
        if (this.engine.replay.isActive && this.engine.activeIdx === this.index) return;

        // Discard if data is totally invalid
        if (!quote || typeof quote !== 'object') return;

        const price = parseFloat(quote.last_price);
        if (isNaN(price) || price <= 0) return;

        const ts = Math.floor(Number(quote.ts_ms) / 1000);
        if (isNaN(ts)) return;

        const duration = this.getIntervalSeconds();
        const candleTime = ts - (ts % duration);

        let ltq = parseInt(quote.ltq || 0);
        if (ltq < 0) ltq = 0;

        // Safeguard against extreme volume spikes (e.g. > 1M in a single tick for indices)
        const isIndex = this.symbol.includes('NIFTY') || this.symbol.includes('SENSEX') || this.symbol.includes('BANKEX');
        if (isIndex && ltq > 1000000) {
            console.warn(`[Chart] Extreme volume spike detected for ${this.symbol}: ${ltq}. Clamping to 0.`);
            ltq = 0;
        }

        if (!this.lastCandle || candleTime > this.lastCandle.time) {
            this.lastCandle = { time: candleTime, open: price, high: price, low: price, close: price, volume: ltq };
        } else if (candleTime === this.lastCandle.time) {
            this.lastCandle.close = price;
            this.lastCandle.high = Math.max(this.lastCandle.high, price);
            this.lastCandle.low = Math.min(this.lastCandle.low, price);
            this.lastCandle.volume += ltq;
        } else {
            // Out of order tick, discard for chart update but could be stored if needed
            return;
        }

        this.fullHistory.candles.set(this.lastCandle.time, { ...this.lastCandle });

        const coloredUpdate = {
            ...this.lastCandle,
            color: this.getColorByRvol(this.lastCandle),
            borderColor: this.getColorByRvol(this.lastCandle),
            wickColor: this.getColorByRvol(this.lastCandle)
        };
        this.mainSeries.update(coloredUpdate);
        this.volumeSeries.update({
            time: this.lastCandle.time, value: this.lastCandle.volume,
            color: this.lastCandle.close >= this.lastCandle.open ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)'
        });
        if (this.activeSymmetrySignal) this.updateSymmetryPnL();
    }

    handleChartUpdate(data) {
        // Block live updates during Replay for the active chart
        if (this.engine.replay.isActive && this.engine.activeIdx === this.index) return;

        if (data.ohlcv) {
            const sortedOhlcv = [...data.ohlcv].sort((a, b) => a[0] - b[0]);

            sortedOhlcv.forEach(v => {
                const ts = Number(v[0]);
                if (isNaN(ts)) return;

                const c = { time: ts, open: v[1], high: v[2], low: v[3], close: v[4], volume: v[5], rvol: v[6] || 1.0 };
                this.fullHistory.candles.set(c.time, c);

                // Safety: Only update series if time is >= last seen time
                if (!this.lastCandle || c.time >= this.lastCandle.time) {
                    const coloredUpdate = {
                        ...c,
                        color: this.getColorByRvol(c),
                        borderColor: this.getColorByRvol(c),
                        wickColor: this.getColorByRvol(c)
                    };

                    try {
                        this.mainSeries.update(coloredUpdate);
                        this.volumeSeries.update({
                            time: c.time, value: c.volume,
                            color: c.close >= c.open ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)'
                        });
                        if (this.activeSymmetrySignal) this.updateSymmetryPnL();
                    } catch (e) {
                        console.warn(`[Chart] Update failed at ${c.time}:`, e.message);
                    }
                    this.lastCandle = c;
                }
            });
        }
        if (data.indicators) {
            this.fullHistory.indicators_raw = data.indicators;
            this.applyIndicators(data.indicators);
            this.updateLegend(data.indicators);
        }
    }

    applyIndicators(indicators, isFullReplace = false) {
        if (!Array.isArray(indicators)) return;
        if (isFullReplace) {
            this.markers = [];
        }
        indicators.forEach(ind => {
            if (ind.id === 'symmetry_signals') {
                this.handleSymmetrySignals(ind.data);
            }
            if (ind.type === 'markers') {
                if (!Array.isArray(ind.data)) return;
                const newMarkers = ind.data.map(m => ({
                    time: Number(m.time), position: m.position, color: m.color, shape: m.shape, text: m.text,
                    sourceId: ind.id
                }));

                if (isFullReplace) {
                    this.markers.push(...newMarkers);
                } else {
                    // Merge markers, avoiding exact duplicates
                    const existingTimes = new Set(this.markers.map(m => `${Number(m.time)}_${m.text}`));
                    newMarkers.forEach(m => {
                        if (!existingTimes.has(`${Number(m.time)}_${m.text}`)) {
                            this.markers.push(m);
                        }
                    });
                }

                this.markers.sort((a, b) => Number(a.time) - Number(b.time));
                this.applyMarkers();
                return;
            }

            if (ind.type === 'price_lines') {
                if (!Array.isArray(ind.data)) return;
                this.indicatorPriceLines = this.indicatorPriceLines || {};
                if (this.indicatorPriceLines[ind.id]) {
                    this.indicatorPriceLines[ind.id].forEach(l => this.mainSeries.removePriceLine(l));
                }
                this.indicatorPriceLines[ind.id] = [];

                if (!this.hiddenPlots.has(ind.id) && this.showIndicators) {
                    ind.data.forEach(lineData => {
                        const line = this.mainSeries.createPriceLine({
                            price: lineData.price,
                            color: lineData.color,
                            lineWidth: lineData.width || 2,
                            lineStyle: 2,
                            axisLabelVisible: !ind.hideLabel,
                            title: ind.hideLabel ? "" : (lineData.title || ind.title)
                        });
                        this.indicatorPriceLines[ind.id].push(line);
                    });
                }
                return;
            }

            if (!Array.isArray(ind.data)) return;

            if (!this.indicatorSeries[ind.id]) {
                const options = {
                    color: ind.style?.color || '#3b82f6',
                    lineWidth: ind.style?.lineWidth || 1,
                    lastValueVisible: false, priceLineVisible: false
                };
                this.indicatorSeries[ind.id] = this.chart.addLineSeries(options);
            }
            const cleanData = ind.data.map(d => ({ ...d, time: Number(d.time) }));
            this.indicatorSeries[ind.id].setData(cleanData);
            this.indicatorSeries[ind.id].applyOptions({ visible: this.showIndicators && !this.hiddenPlots.has(ind.id) });
        });
    }

    handleSymmetrySignals(data) {
        if (!data || data.length === 0) {
            this.activeSymmetrySignal = null;
            this.updateSymmetryUI();
            return;
        }
        // Take the latest signal
        const latest = data[data.length - 1];
        this.activeSymmetrySignal = latest;

        // Add SL/TP lines
        this.indicatorPriceLines = this.indicatorPriceLines || {};
        if (this.indicatorPriceLines['sym_sl']) {
            this.mainSeries.removePriceLine(this.indicatorPriceLines['sym_sl']);
        }
        if (this.indicatorPriceLines['sym_tp']) {
            this.mainSeries.removePriceLine(this.indicatorPriceLines['sym_tp']);
        }

        if (latest.sl && this.showIndicators) {
            this.indicatorPriceLines['sym_sl'] = this.mainSeries.createPriceLine({
                price: latest.sl, color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SYM SL'
            });
        }
        if (latest.tp && this.showIndicators) {
            this.indicatorPriceLines['sym_tp'] = this.mainSeries.createPriceLine({
                price: latest.tp, color: '#3b82f6', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SYM TP'
            });
        }

        this.updateSymmetryUI();
    }

    updateSymmetryUI() {
        if (this.index !== this.engine.activeIdx) return;

        const activeEl = document.getElementById('symmetryActiveSignal');
        const noEl = document.getElementById('noSymmetrySignal');
        if (!activeEl || !noEl) return;

        if (this.activeSymmetrySignal) {
            activeEl.classList.remove('hidden');
            noEl.classList.add('hidden');

            document.getElementById('symType').innerText = this.activeSymmetrySignal.signal_type || 'BUY';
            document.getElementById('symScore').innerText = `Score: ${this.activeSymmetrySignal.score}/4`;
            document.getElementById('symSL').innerText = (this.activeSymmetrySignal.sl || 0).toFixed(2);
            document.getElementById('symTP').innerText = (this.activeSymmetrySignal.tp || 0).toFixed(2);

            // Initial PnL
            this.updateSymmetryPnL();
        } else {
            activeEl.classList.add('hidden');
            noEl.classList.remove('hidden');
        }
    }

    updateSymmetryPnL() {
        if (!this.activeSymmetrySignal || !this.lastCandle) return;

        const currentPrice = this.lastCandle.close;
        const entryPrice = this.activeSymmetrySignal.entry_price || currentPrice;

        // For an option buyer, PnL is always (Current - Entry) regardless of Call or Put
        const pnlPct = ((currentPrice - entryPrice) / entryPrice) * 100;

        const pnlEl = document.getElementById('symPnL');
        if (pnlEl) {
            pnlEl.innerText = `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%`;
            pnlEl.className = `text-xs font-black ${pnlPct >= 0 ? 'text-green-500' : 'text-red-500'}`;
        }
    }

    applyMarkers() {
        if (!this.showIndicators) {
            this.mainSeries.setMarkers([]);
            return;
        }
        const visibleMarkers = this.markers.filter(m => !this.hiddenPlots.has(m.sourceId));
        this.mainSeries.setMarkers(visibleMarkers);
    }

    addHorizontalLine(price, color = '#3b82f6') {
        const line = this.mainSeries.createPriceLine({
            price, color, lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: 'HLINE'
        });
        this.drawings.push({ price, color, line });
        this.engine.saveLayout();
    }

    getIntervalSeconds() {
        const m = {
            '1': 60, '3': 180, '5': 300, '15': 900, '30': 1800,
            '60': 3600, '120': 7200, '240': 14400, 'D': 86400, 'W': 604800
        };
        return m[this.interval] || 60;
    }

    async toggleOIProfile(visible) {
        this.showOIProfile = visible;
        this.oiLines.forEach(l => this.mainSeries.removePriceLine(l));
        this.oiLines = [];

        if (visible) {
            const data = await this.engine.dataManager.fetchOIProfile(this.symbol);
            if (data && data.chain && data.spot_price) {
                const spot = data.spot_price;
                const strikes = [...new Set(data.chain.map(c => c.strike))].sort((a, b) => a - b);

                let atmIdx = 0;
                let minDiff = Infinity;
                strikes.forEach((s, i) => {
                    const diff = Math.abs(s - spot);
                    if (diff < minDiff) { minDiff = diff; atmIdx = i; }
                });

                const start = Math.max(0, atmIdx - 10);
                const end = Math.min(strikes.length, atmIdx + 11);
                const targetStrikes = strikes.slice(start, end);

                targetStrikes.forEach(strike => {
                    const call = data.chain.find(c => c.strike === strike && c.option_type === 'call');
                    const put = data.chain.find(c => c.strike === strike && c.option_type === 'put');

                    if (call && call.oi > 0) {
                        this.oiLines.push(this.mainSeries.createPriceLine({
                            price: strike, color: 'rgba(239, 68, 68, 0.4)', lineWidth: 1, lineStyle: 0,
                            axisLabelVisible: true, title: `C-OI: ${(call.oi/1000000).toFixed(1)}M`
                        }));
                    }
                    if (put && put.oi > 0) {
                        this.oiLines.push(this.mainSeries.createPriceLine({
                            price: strike, color: 'rgba(34, 197, 94, 0.4)', lineWidth: 1, lineStyle: 0,
                            axisLabelVisible: true, title: `P-OI: ${(put.oi/1000000).toFixed(1)}M`
                        }));
                    }
                });
            }
        }
    }

    addLocalControls() {
        const wrapper = this.container.parentElement;
        const controls = document.createElement('div');
        controls.className = 'chart-controls';

        const zoomOut = document.createElement('button');
        zoomOut.className = 'chart-ctrl-btn';
        zoomOut.title = 'Zoom Out';
        zoomOut.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12H4"/></svg>`;
        zoomOut.onclick = (e) => {
            e.stopPropagation();
            const ts = this.chart.timeScale();
            ts.applyOptions({ barSpacing: Math.max(0.5, ts.options().barSpacing / 1.2) });
        };

        const zoomIn = document.createElement('button');
        zoomIn.className = 'chart-ctrl-btn';
        zoomIn.title = 'Zoom In';
        zoomIn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>`;
        zoomIn.onclick = (e) => {
            e.stopPropagation();
            const ts = this.chart.timeScale();
            ts.applyOptions({ barSpacing: Math.min(50, ts.options().barSpacing * 1.2) });
        };

        const reset = document.createElement('button');
        reset.className = 'chart-ctrl-btn';
        reset.title = 'Fit Content';
        reset.innerHTML = `<span class="text-[9px] font-black px-1">FIT</span>`;
        reset.onclick = (e) => { e.stopPropagation(); this.chart.timeScale().fitContent(); };

        controls.appendChild(zoomOut);
        controls.appendChild(reset);
        controls.appendChild(zoomIn);
        wrapper.appendChild(controls);
    }

    createLegend() {
        const wrapper = this.container.parentElement;
        this.legend = document.createElement('div');
        this.legend.className = 'absolute top-12 left-2 z-20 flex flex-col gap-1 pointer-events-none';
        this.legend.style.fontFamily = "'Plus Jakarta Sans', sans-serif";
        wrapper.appendChild(this.legend);
    }

    updateLegend(indicators) {
        if (!this.legend) return;
        this.legend.innerHTML = '';
        if (!this.showIndicators || !indicators) return;

        const proPatterns = ['ema_', 'volume_', 'evwma', 'dyn_pivot'];
        const normalIndicators = indicators.filter(ind => !proPatterns.some(p => ind.id.toLowerCase().startsWith(p)));
        const proIndicators = indicators.filter(ind => proPatterns.some(p => ind.id.toLowerCase().startsWith(p)));

        const renderItem = (ind, parent) => {
            const isHidden = this.hiddenPlots.has(ind.id);
            const item = document.createElement('div');
            item.className = `flex items-center gap-2 px-2 py-0.5 rounded cursor-pointer transition-all ${isHidden ? 'opacity-40 bg-black/20' : 'bg-black/40 hover:bg-black/60'} backdrop-blur-sm border border-white/5`;
            item.style.pointerEvents = 'auto';
            item.title = isHidden ? 'Show Indicator' : 'Hide Indicator';

            item.onclick = (e) => {
                e.stopPropagation();
                if (this.hiddenPlots.has(ind.id)) this.hiddenPlots.delete(ind.id);
                else this.hiddenPlots.add(ind.id);

                let targetIndicators = this.fullHistory.indicators_raw;
                if (this.engine.replay.isActive) {
                    const currentTs = this.engine.replay.fullData[this.engine.replay.currentIndex - 1]?.time || 0;
                    targetIndicators = targetIndicators.map(i => ({
                        ...i, data: i.data ? i.data.filter(d => Number(d.time) <= Number(currentTs)) : []
                    }));
                }
                this.applyIndicators(targetIndicators, true);
                this.updateLegend(targetIndicators);
            };

            const dot = document.createElement('div');
            dot.className = 'w-1.5 h-1.5 rounded-full';
            dot.style.backgroundColor = ind.style?.color || (ind.data && ind.data[0]?.color) || '#3b82f6';

            const text = document.createElement('span');
            text.className = 'text-[9px] font-black text-gray-300 uppercase tracking-tighter';
            text.innerText = ind.title || ind.id;

            item.appendChild(dot);
            item.appendChild(text);
            parent.appendChild(item);
        };

        normalIndicators.forEach(ind => renderItem(ind, this.legend));

        if (proIndicators.length > 0) {
            const container = document.createElement('div');
            container.className = 'flex items-center gap-1';
            container.style.pointerEvents = 'auto';

            const proHeader = document.createElement('div');
            const allHidden = proIndicators.every(ind => this.hiddenPlots.has(ind.id));
            proHeader.className = `flex items-center gap-2 px-2 py-0.5 rounded cursor-pointer transition-all ${allHidden ? 'opacity-40 bg-blue-500/10' : 'bg-blue-600/40 hover:bg-blue-600/60'} backdrop-blur-sm border border-blue-500/20`;
            proHeader.innerHTML = `<span class="text-[9px] font-black text-blue-300 uppercase italic">PRO-ANALYSIS</span>`;
            proHeader.onclick = (e) => {
                e.stopPropagation();
                const targetState = !allHidden;
                proIndicators.forEach(ind => {
                    if (targetState) this.hiddenPlots.add(ind.id);
                    else this.hiddenPlots.delete(ind.id);
                });
                this.applyIndicators(this.fullHistory.indicators_raw, true);
                this.updateLegend(this.fullHistory.indicators_raw);
            };

            const gear = document.createElement('button');
            gear.className = 'p-1 rounded bg-black/40 hover:bg-white/10 text-gray-400 transition-colors border border-white/5';
            gear.innerHTML = `<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>`;
            gear.onclick = (e) => {
                e.stopPropagation();
                this.engine.showSettingsModal();
            };

            container.appendChild(proHeader);
            container.appendChild(gear);
            this.legend.appendChild(container);
        }
    }

    destroy() {
        if (this.chart) this.chart.remove();
    }
}

class ReplayController {
    constructor(engine) {
        this.engine = engine;
        this.isActive = false;
        this.isPlaying = false;
        this.currentIndex = 0;
        this.fullData = [];
        this.intervalId = null;
    }

    start(data) {
        if (!data || data.length === 0) {
            console.warn("[Replay] No data available for replay");
            return;
        }
        this.isActive = true;
        this.isPlaying = false;
        this.fullData = data;
        // Start showing all candles initially so user can click one
        this.currentIndex = data.length;
        this.updateUI();
    }

    setStartPoint(time) {
        const index = this.fullData.findIndex(c => Number(c.time) >= Number(time));
        if (index !== -1) {
            this.currentIndex = index + 1;
            this.renderState();
            this.updateUI();
            console.log("[Replay] Start point set to index:", this.currentIndex);
        }
    }

    renderState() {
        const chart = this.engine.charts[this.engine.activeIdx];
        if (!chart) return;

        const currentTs = this.fullData[this.currentIndex - 1]?.time || 0;
        const slice = this.fullData.slice(0, this.currentIndex);
        const coloredCandles = slice.map(c => ({
            ...c,
            time: Number(c.time),
            color: chart.getColorByRvol(c),
            borderColor: chart.getColorByRvol(c),
            wickColor: chart.getColorByRvol(c)
        }));

        try {
            chart.mainSeries.setData(coloredCandles);

            const volumes = slice.map(c => ({
                time: Number(c.time), value: c.volume,
                color: c.close >= c.open ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)'
            }));
            chart.volumeSeries.setData(volumes);

            // Sliced Indicators
            if (chart.fullHistory.indicators_raw) {
                const slicedIndicators = chart.fullHistory.indicators_raw.map(ind => {
                    if (!ind.data || !Array.isArray(ind.data)) return ind;
                    return {
                        ...ind,
                        data: ind.data.filter(d => Number(d.time) <= Number(currentTs))
                    };
                });
                chart.applyIndicators(slicedIndicators, true);
                chart.updateLegend(slicedIndicators);
            }
        } catch (e) {
            console.error("[Replay] renderState failed:", e);
        }
    }

    togglePlay() {
        if (!this.isActive || this.currentIndex >= this.fullData.length) return;

        this.isPlaying = !this.isPlaying;
        console.log("[Replay] Toggle Play:", this.isPlaying);

        if (this.isPlaying) {
            this.intervalId = setInterval(() => this.next(), 1000);
        } else {
            if (this.intervalId) clearInterval(this.intervalId);
        }
        this.updateUI();
    }

    next() {
        if (this.currentIndex < this.fullData.length) {
            this.currentIndex++;
            this.renderState();
        } else {
            console.log("[Replay] End of data reached");
            this.isPlaying = false;
            if (this.intervalId) clearInterval(this.intervalId);
        }
        this.updateUI();
    }

    prev() {
        if (this.currentIndex > 1) {
            this.currentIndex--;
            this.renderState();
        }
        this.updateUI();
    }

    exit() {
        this.isActive = false;
        this.isPlaying = false;
        if (this.intervalId) clearInterval(this.intervalId);
        const chart = this.engine.charts[this.engine.activeIdx];
        if (chart) {
            chart.renderData();
            if (chart.fullHistory.indicators_raw) {
                chart.applyIndicators(chart.fullHistory.indicators_raw, true);
                chart.updateLegend(chart.fullHistory.indicators_raw);
            }
        }
        this.updateUI();
    }

    updateUI() {
        const controls = document.getElementById('replayControls');
        const normal = document.getElementById('normalControls');
        if (controls && normal) {
            controls.classList.toggle('hidden', !this.isActive);
            normal.classList.toggle('hidden', this.isActive);
        }

        const pIcon = document.getElementById('playIcon');
        const paIcon = document.getElementById('pauseIcon');
        if (pIcon && paIcon) {
            pIcon.classList.toggle('hidden', this.isPlaying);
            paIcon.classList.toggle('hidden', !this.isPlaying);
        }

        const status = document.getElementById('replayStatus');
        if (status) {
            if (this.isActive) {
                if (this.currentIndex === this.fullData.length) {
                    status.innerText = "CLICK BAR TO SET START POINT";
                    status.style.color = "#fbbf24"; // Amber
                } else {
                    status.innerText = `REPLAY: ${this.currentIndex}/${this.fullData.length}`;
                    status.style.color = "";
                }
            } else {
                status.innerText = 'REPLAY';
            }
        }

        ['replayPrevBtn', 'replayPlayBtn', 'replayNextBtn'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.disabled = !this.isActive || this.currentIndex === this.fullData.length;
        });
    }
}

class MultiChartEngine {
    constructor() {
        this.charts = [];
        this.activeIdx = 0;
        this.layout = 1;
        this.dataManager = new DataManager(this);
        this.replay = new ReplayController(this);
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupSearch();
        this.loadLayout();
        window.addEventListener('resize', () => {
            this.charts.forEach(c => c.chart.resize(c.container.clientWidth, c.container.clientHeight));
        });
    }

    setupSearch() {
        const searchInput = document.getElementById('symbolSearch');
        const resultsDiv = document.getElementById('searchResults');
        let debounceTimer;
        let selectedIndex = -1;

        searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            const query = e.target.value.trim();
            if (query.length < 2) {
                resultsDiv.classList.add('hidden');
                return;
            }

            debounceTimer = setTimeout(async () => {
                try {
                    const res = await fetch(`/api/tv/search?text=${encodeURIComponent(query)}`);
                    const data = await res.json();
                    this.renderSearchResults(data.symbols || []);
                    selectedIndex = -1;
                } catch (err) {
                    console.error("[Search] Failed:", err);
                }
            }, 300);
        });

        searchInput.addEventListener('keydown', async (e) => {
            const items = resultsDiv.querySelectorAll('.search-item');

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
                this.updateSearchSelection(items, selectedIndex);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIndex = Math.max(selectedIndex - 1, 0);
                this.updateSearchSelection(items, selectedIndex);
            } else if (e.key === 'Enter') {
                if (selectedIndex >= 0 && items[selectedIndex]) {
                    items[selectedIndex].click();
                } else {
                    const sym = searchInput.value.trim().toUpperCase();
                    if (sym) {
                        await this.charts[this.activeIdx].switchSymbol(sym);
                        this.saveLayout();
                        resultsDiv.classList.add('hidden');
                    }
                }
            } else if (e.key === 'Escape') {
                resultsDiv.classList.add('hidden');
            }
        });

        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !resultsDiv.contains(e.target)) {
                resultsDiv.classList.add('hidden');
            }
        });
    }

    renderSearchResults(symbols) {
        const resultsDiv = document.getElementById('searchResults');
        if (!symbols.length) {
            resultsDiv.classList.add('hidden');
            return;
        }

        resultsDiv.innerHTML = symbols.map((s, i) => `
            <div class="search-item p-3 flex items-center justify-between cursor-pointer border-b border-white/5 hover:bg-blue-500/10 transition-colors"
                 data-symbol="${s.symbol}" data-exchange="${s.exchange}">
                <div class="flex flex-col">
                    <span class="text-xs font-black text-white">${s.symbol}</span>
                    <span class="text-[10px] text-gray-500 truncate max-w-[250px]">${s.description || ''}</span>
                </div>
                <div class="flex items-center gap-2">
                    <span class="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 uppercase border border-white/5">${s.exchange}</span>
                    <span class="text-[9px] font-black text-blue-500/70 uppercase italic tracking-tighter">${s.type || ''}</span>
                </div>
            </div>
        `).join('');

        resultsDiv.querySelectorAll('.search-item').forEach(item => {
            item.addEventListener('click', async () => {
                const sym = item.dataset.symbol;
                const exch = item.dataset.exchange;
                const fullSym = exch ? `${exch}:${sym}` : sym;

                document.getElementById('symbolSearch').value = fullSym;
                await this.charts[this.activeIdx].switchSymbol(fullSym);
                this.saveLayout();
                resultsDiv.classList.add('hidden');
            });
        });

        resultsDiv.classList.remove('hidden');
    }

    updateSearchSelection(items, index) {
        items.forEach((item, i) => {
            item.classList.toggle('bg-blue-500/20', i === index);
            if (i === index) item.scrollIntoView({ block: 'nearest' });
        });
    }

    setupEventListeners() {
        document.querySelectorAll('.layout-btn').forEach(btn => {
            btn.addEventListener('click', () => this.setLayout(parseInt(btn.dataset.layout)));
        });

        document.querySelectorAll('.tf-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const c = this.charts[this.activeIdx];
                if (c) {
                    // Visual feedback
                    document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    await c.switchSymbol(c.symbol, btn.dataset.interval);
                    this.saveLayout();
                }
            });
        });


        document.getElementById('chartTypeSelector').addEventListener('change', (e) => {
            this.charts[this.activeIdx].setChartType(e.target.value);
            this.saveLayout();
        });

        document.getElementById('oiProfileToggle').addEventListener('change', (e) => {
            this.charts.forEach(c => c.toggleOIProfile(e.target.checked));
        });

        document.getElementById('analysisToggle').addEventListener('change', (e) => {
            this.charts.forEach(c => {
                c.showIndicators = e.target.checked;
                if (c.fullHistory.indicators_raw) c.applyIndicators(c.fullHistory.indicators_raw);
                c.applyMarkers();
            });
        });


        document.getElementById('themeToggleBtn').addEventListener('click', () => {
            const isLight = document.body.classList.toggle('light-theme');
            localStorage.setItem('theme', isLight ? 'light' : 'dark');
            this.applyTheme();
        });

        // Replay Controls
        document.getElementById('replayModeBtn').addEventListener('click', async () => {
            const c = this.charts[this.activeIdx];
            const data = Array.from(c.fullHistory.candles.values()).sort((a,b) => a.time - b.time);
            this.replay.start(data);
        });

        document.getElementById('replayPlayBtn').addEventListener('click', () => this.replay.togglePlay());
        document.getElementById('replayNextBtn').addEventListener('click', () => this.replay.next());
        document.getElementById('replayPrevBtn').addEventListener('click', () => this.replay.prev());
        document.getElementById('exitReplayBtn').addEventListener('click', () => this.replay.exit());

        document.getElementById('maximizeBtn')?.addEventListener('click', () => {
            const c = this.charts[this.activeIdx];
            if (c) {
                const url = `/?symbol=${encodeURIComponent(c.symbol)}&interval=${c.interval}`;
                window.open(url, '_blank');
            }
        });

        // Analysis Settings Modal
        document.getElementById('applyAnalysisBtn')?.addEventListener('click', () => this.applyAnalysisSettings());
        document.getElementById('resetAnalysisBtn')?.addEventListener('click', () => {
            localStorage.removeItem('pro_analysis_settings');
            document.getElementById('analysisSettingsModal').classList.add('hidden');
            this.charts.forEach(c => c.switchSymbol(c.symbol, c.interval));
        });
        document.getElementById('closeAnalysisBtn')?.addEventListener('click', () => {
            document.getElementById('analysisSidebar').classList.add('hidden');
        });
        document.getElementById('closeSettingsBtn')?.addEventListener('click', () => {
            document.getElementById('analysisSettingsModal').classList.add('hidden');
        });
    }

    saveLayout() {
        if (window.INITIAL_CONFIG && window.INITIAL_CONFIG.symbol && window.INITIAL_CONFIG.symbol !== "None" && window.INITIAL_CONFIG.symbol !== "") {
            return; // Don't save if in single chart pop-out mode
        }
        localStorage.setItem('prodesk_layout', this.layout);
        this.charts.forEach((c, i) => {
            localStorage.setItem(`chart_config_${i}`, JSON.stringify({
                symbol: c.symbol, interval: c.interval, chartType: c.chartType
            }));
        });
    }

    setLayout(n) {
        this.layout = n;
        const container = document.getElementById('chartsContainer');
        container.innerHTML = '';
        this.charts.forEach(c => c.destroy());
        this.charts = [];

        const rows = n === 4 ? 2 : 1;
        const cols = n === 1 ? 1 : 2;
        container.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
        container.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

        for (let i = 0; i < n; i++) {
            const wrapper = document.createElement('div');
            wrapper.className = 'chart-wrapper';
            const div = document.createElement('div');
            div.id = `chart-${i}`;
            div.className = 'chart-container';
            wrapper.appendChild(div);
            container.appendChild(wrapper);

            const c = new ChartInstance(div.id, i, this);
            this.charts.push(c);

            const saved = JSON.parse(localStorage.getItem(`chart_config_${i}`));
            if (i === 0 && window.INITIAL_CONFIG && window.INITIAL_CONFIG.symbol !== "None") {
                // Use URL params for the primary chart
                c.switchSymbol(window.INITIAL_CONFIG.symbol, window.INITIAL_CONFIG.interval);
            } else if (saved) {
                c.symbol = saved.symbol;
                c.interval = saved.interval;
                c.chartType = saved.chartType;
                c.switchSymbol(c.symbol, c.interval);
            } else {
                c.switchSymbol('NSE:NIFTY', '1');
            }
        }
        this.setActiveChart(0);
        this.saveLayout();
    }

    setActiveChart(idx) {
        this.activeIdx = idx;
        document.querySelectorAll('.chart-wrapper').forEach((w, i) => {
            w.classList.toggle('active', i === idx);
        });
        this.updateUI();
        if (this.charts[idx]) this.charts[idx].updateSymmetryUI();
    }

    updateUI() {
        const c = this.charts[this.activeIdx];
        if (!c) return;
        document.querySelectorAll('.tf-btn').forEach(b => b.classList.toggle('active', b.dataset.interval === c.interval));
        document.getElementById('symbolSearch').value = c.symbol;
        document.getElementById('chartTypeSelector').value = c.chartType;

        this.charts.forEach(chart => {
            const wrapper = chart.container.parentElement;
            let label = wrapper.querySelector('.chart-label');
            if (!label) {
                label = document.createElement('div');
                label.className = 'chart-label';
                wrapper.appendChild(label);
            }
            const isDailyOrWeekly = chart.interval === 'D' || chart.interval === 'W';
            const suffix = isDailyOrWeekly ? '' : 'm';
            label.innerText = `${chart.symbol} (${chart.interval}${suffix})`;
        });
    }

    applyTheme() {
        const isLight = document.body.classList.contains('light-theme');
        const bg = isLight ? '#f8fafc' : '#0f172a';
        const text = isLight ? '#1e293b' : '#d1d5db';
        const grid = isLight ? '#f1f5f9' : 'rgba(255,255,255,0.05)';

        this.charts.forEach(c => {
            c.chart.applyOptions({
                layout: { background: { color: bg }, textColor: text },
                grid: { vertLines: { color: grid }, horzLines: { color: grid } }
            });
        });
    }

    showSettingsModal() {
        const modal = document.getElementById('analysisSettingsModal');
        if (!modal) return;

        const settings = JSON.parse(localStorage.getItem('pro_analysis_settings') || '{}');
        const inputs = modal.querySelectorAll('input');
        inputs.forEach(input => {
            if (settings[input.id] !== undefined) {
                if (input.type === 'checkbox') input.checked = settings[input.id];
                else input.value = settings[input.id];
            }
        });

        modal.classList.remove('hidden');
    }

    applyAnalysisSettings() {
        const modal = document.getElementById('analysisSettingsModal');
        const inputs = modal.querySelectorAll('input');
        const settings = {};
        inputs.forEach(input => {
            settings[input.id] = input.type === 'checkbox' ? input.checked : input.value;
        });

        localStorage.setItem('pro_analysis_settings', JSON.stringify(settings));
        modal.classList.add('hidden');

        // Refresh all charts
        this.charts.forEach(c => c.switchSymbol(c.symbol, c.interval));
    }

    setLoading(show) {
        document.getElementById('loading').classList.toggle('hidden', !show);
    }


    loadLayout() {
        const theme = localStorage.getItem('theme') || 'dark';
        document.body.classList.toggle('light-theme', theme === 'light');

        if (window.INITIAL_CONFIG && window.INITIAL_CONFIG.symbol && window.INITIAL_CONFIG.symbol !== "None" && window.INITIAL_CONFIG.symbol !== "") {
            this.setLayout(1);
        } else {
            const saved = localStorage.getItem('prodesk_layout');
            this.setLayout(saved ? parseInt(saved) : 1);
        }
    }
}

// Bootstrap
window.addEventListener('DOMContentLoaded', () => {
    window.prodeskEngine = new MultiChartEngine();
});
