/**
 * PRODESK Options Dashboard v3.0
 * Unified management of Option Chain, Analysis, Strategies, and Scalper.
 */

class OptionsDashboardManager {
    constructor() {
        this.currentUnderlying = 'NSE:NIFTY';
        this.socket = null;
        this.charts = {};
        this.theme = localStorage.getItem('theme') || 'dark';

        this.colors = {
            ce: '#ef4444', // red-500 (Resistance)
            pe: '#10b981', // emerald-500 (Support)
            spot: '#94a3b8', // slate-400
            diff: '#3b82f6'  // blue-500
        };

        // Chart.js defaults
        if (window.Chart) {
            Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";
            Chart.defaults.color = '#94a3b8';
            Chart.defaults.font.size = 9;
        }

        this.init();
    }

    async init() {
        this.applyTheme(this.theme);
        this.initSocket();
        this.setupEventListeners();
        await this.loadData();

        // Auto-refresh
        setInterval(() => this.loadData(), 120000);
    }

    initSocket() {
        this.socket = io();
        this.socket.on('connect', () => {
            console.log("[Options] Socket connected");
            this.socket.emit('subscribe_options', { underlying: this.currentUnderlying });
            this.socket.emit('subscribe', { instrumentKeys: [this.currentUnderlying], interval: '1' });
        });

        this.socket.on('raw_tick', (data) => {
            if (data[this.currentUnderlying]) {
                const price = parseFloat(data[this.currentUnderlying].last_price);
                if (price > 0) document.getElementById('spotPrice').textContent = price.toLocaleString(undefined, {minimumFractionDigits: 2});
            }
        });

        this.socket.on('chart_update', (data) => {
            if (data.instrumentKey === this.currentUnderlying && data.ohlcv?.length > 0) {
                const price = parseFloat(data.ohlcv[data.ohlcv.length - 1][4]);
                if (price > 0) document.getElementById('spotPrice').textContent = price.toLocaleString(undefined, {minimumFractionDigits: 2});
            }
        });

        this.socket.on('options_alert', (data) => alert(data.message));
    }

    setupEventListeners() {
        // Core controls
        document.getElementById('underlyingSelect').addEventListener('change', (e) => this.switchUnderlying(e.target.value));
        document.getElementById('refreshBtn').addEventListener('click', () => this.loadData());
        document.getElementById('backfillBtn').addEventListener('click', () => this.triggerBackfill());
        document.getElementById('optionsThemeToggle').addEventListener('click', () => this.toggleTheme());

        // Navigation removed
    }

    async switchUnderlying(newUnderlying) {
        this.socket.emit('unsubscribe_options', { underlying: this.currentUnderlying });
        this.socket.emit('unsubscribe', { instrumentKeys: [this.currentUnderlying], interval: '1' });

        this.currentUnderlying = newUnderlying;

        this.socket.emit('subscribe_options', { underlying: this.currentUnderlying });
        this.socket.emit('subscribe', { instrumentKeys: [this.currentUnderlying], interval: '1' });

        await this.loadData();
    }

    async loadData() {
        try {
            const [genie, detailedTrend, oiAnalysis, pcrTrend] = await Promise.all([
                fetch(`/api/options/genie-insights/${this.currentUnderlying}`).then(r => r.json()),
                fetch(`/api/options/oi-trend-detailed/${this.currentUnderlying}`).then(r => r.json()),
                fetch(`/api/options/oi-analysis/${this.currentUnderlying}`).then(r => r.json()),
                fetch(`/api/options/pcr-trend/${this.currentUnderlying}`).then(r => r.json())
            ]);

            this.renderGenieCard(genie);
            this.renderCEvsPEChangeChart(detailedTrend);
            this.renderOIDiffChart(detailedTrend);
            this.renderStrikeWiseCharts(oiAnalysis);
            this.renderPCRTrend(pcrTrend);

            document.getElementById('dataSource').textContent = 'Live Feed';
            document.getElementById('lastUpdated').textContent = new Date().toLocaleTimeString('en-IN', { hour12: false });
        } catch (e) { console.error("[Options] Load failed:", e); }
    }

    // Removed renderOptionChain

    renderGenieCard(data) {
        const el = document.getElementById('genieControl');
        if (!el) return;
        el.textContent = data.control.replace(/_/g, ' ');
        el.className = `text-lg font-black uppercase ${data.control.includes('BUYERS') ? 'text-green-500' : data.control.includes('SELLERS') ? 'text-red-500' : 'text-white'}`;
        document.getElementById('genieDistribution').textContent = data.distribution.status;
        document.getElementById('genieRange').textContent = `${data.boundaries.lower} - ${data.boundaries.upper}`;

        // Sync Spot Sentiment
        const spotSent = document.getElementById('spotSentiment');
        if (spotSent) {
            spotSent.textContent = data.sentiment;
            spotSent.className = `text-[8px] font-black px-1.5 py-0.5 rounded uppercase ${data.sentiment === 'BULLISH' ? 'bg-green-500/20 text-green-500' : data.sentiment === 'BEARISH' ? 'bg-red-500/20 text-red-500' : 'bg-gray-500/20 text-gray-400'}`;
        }

        // Target (Aim) removed from UI

        // Max Pain
        const mpEl = document.getElementById('maxPain');
        if (mpEl) mpEl.textContent = data.max_pain.toLocaleString();

        // Sideways badge
        document.getElementById('sidewaysBadge')?.classList.toggle('hidden', !data.sideways_expected);
    }

    // Removed buildup and iv rendering

    renderCEvsPEChangeChart(data) {
        const ctx = document.getElementById('ceVsPeChangeChart')?.getContext('2d');
        if (!ctx) return;
        if (this.charts.ceVsPe) this.charts.ceVsPe.destroy();

        const history = data.history || [];
        const labels = history.map(h => new Date(h.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }));

        this.charts.ceVsPe = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'CE OI Chg', data: history.map(h => h.ce_oi_change), borderColor: this.colors.ce, backgroundColor: this.colors.ce + '1A', fill: false, tension: 0.3, pointRadius: 0, yAxisID: 'y' },
                    { label: 'PE OI Chg', data: history.map(h => h.pe_oi_change), borderColor: this.colors.pe, backgroundColor: this.colors.pe + '1A', fill: false, tension: 0.3, pointRadius: 0, yAxisID: 'y' },
                    { label: 'Spot', data: history.map(h => h.spot_price), borderColor: this.theme === 'light' ? '#f59e0b' : '#fff', borderDash: [5, 5], borderWidth: 1, pointRadius: 0, yAxisID: 'y1' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
                    y: { type: 'linear', position: 'left', ticks: { font: { size: 8 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
                    y1: { type: 'linear', position: 'right', beginAtZero: false, grid: { display: false }, ticks: { font: { size: 8 } } }
                },
                plugins: { legend: { position: 'top', labels: { boxWidth: 8, font: { size: 8 } } } }
            }
        });
    }

    renderPCRTrend(data) {
        const ctx = document.getElementById('pcrTrendChart')?.getContext('2d');
        if (!ctx) return;
        if (this.charts.pcrTrend) this.charts.pcrTrend.destroy();

        const history = data.history || [];
        if (history.length === 0) return;

        const lastValue = history[history.length - 1].pcr_oi;
        const pcrEl = document.getElementById('currentPcrValue');
        if (pcrEl) {
            pcrEl.textContent = lastValue.toFixed(2);
            pcrEl.className = `text-[10px] font-black ${lastValue > 1 ? 'text-green-500' : lastValue < 0.7 ? 'text-red-500' : 'text-blue-500'}`;
        }

        const labels = history.map(h => new Date(h.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }));

        this.charts.pcrTrend = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    data: history.map(h => h.pcr_oi),
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    borderWidth: 1.5
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { enabled: true } },
                scales: {
                    x: { display: false },
                    y: {
                        display: true,
                        position: 'right',
                        grid: { display: false },
                        ticks: { display: true, font: { size: 7 }, count: 2, color: '#94a3b8' }
                    }
                }
            }
        });
    }

    renderOIDiffChart(data) {
        const ctx = document.getElementById('oiDiffChart')?.getContext('2d');
        if (!ctx) return;
        if (this.charts.oiDiff) this.charts.oiDiff.destroy();

        const history = data.history || [];
        const labels = history.map(h => new Date(h.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }));

        this.charts.oiDiff = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'PE-CE Diff', data: history.map(h => h.pe_oi_change - h.ce_oi_change), borderColor: this.colors.diff, backgroundColor: this.colors.diff + '1A', fill: true, tension: 0.3, pointRadius: 0, yAxisID: 'y' },
                    { label: 'Spot', data: history.map(h => h.spot_price), borderColor: this.theme === 'light' ? '#f59e0b' : '#fff', borderDash: [5, 5], borderWidth: 1, pointRadius: 0, yAxisID: 'y1' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
                    y: { type: 'linear', position: 'left', ticks: { font: { size: 8 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
                    y1: { type: 'linear', position: 'right', beginAtZero: false, grid: { display: false }, ticks: { font: { size: 8 } } }
                },
                plugins: { legend: { position: 'top', labels: { boxWidth: 8, font: { size: 8 } } } }
            }
        });
    }

    renderStrikeWiseCharts(data) {
        this.renderStrikeWiseOiChange(data);
        this.renderStrikeWiseTotalOi(data);
        this.updateSidebars(data.totals);
    }

    renderStrikeWiseOiChange(data) {
        const ctx = document.getElementById('strikeWiseOiChangeChart')?.getContext('2d');
        if (!ctx) return;
        if (this.charts.strikeOiChg) this.charts.strikeOiChg.destroy();

        const oiData = data.data || [];
        this.charts.strikeOiChg = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: oiData.map(d => d.strike),
                datasets: [
                    { label: 'CE OI Chg', data: oiData.map(d => d.call_oi_change), backgroundColor: this.colors.ce + 'B3' },
                    { label: 'PE OI Chg', data: oiData.map(d => d.put_oi_change), backgroundColor: this.colors.pe + 'B3' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 8 }, maxRotation: 45 } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 8 } } }
                },
                plugins: { legend: { display: false } }
            }
        });
    }

    renderStrikeWiseTotalOi(data) {
        const ctx = document.getElementById('strikeWiseTotalOiChart')?.getContext('2d');
        if (!ctx) return;
        if (this.charts.strikeTotalOi) this.charts.strikeTotalOi.destroy();

        const oiData = data.data || [];
        this.charts.strikeTotalOi = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: oiData.map(d => d.strike),
                datasets: [
                    { label: 'CE Total OI', data: oiData.map(d => d.call_oi), backgroundColor: this.colors.ce + 'B3' },
                    { label: 'PE Total OI', data: oiData.map(d => d.put_oi), backgroundColor: this.colors.pe + 'B3' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 8 }, maxRotation: 45 } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 8 } } }
                },
                plugins: { legend: { display: false } }
            }
        });
    }

    updateSidebars(totals) {
        if (!totals) return;

        const format = (v) => {
            if (Math.abs(v) >= 10000000) return (v / 10000000).toFixed(2) + 'Cr';
            if (Math.abs(v) >= 100000) return (v / 100000).toFixed(2) + 'L';
            if (Math.abs(v) >= 1000) return (v / 1000).toFixed(1) + 'K';
            return v;
        };

        // Change Sidebar
        document.getElementById('totalCallOiChg').textContent = format(totals.total_call_oi_chg);
        document.getElementById('totalPutOiChg').textContent = format(totals.total_put_oi_chg);

        const chgMax = Math.max(Math.abs(totals.total_call_oi_chg), Math.abs(totals.total_put_oi_chg), 1);
        document.getElementById('callChgBar').style.width = (Math.abs(totals.total_call_oi_chg) / chgMax * 100) + '%';
        document.getElementById('putChgBar').style.width = (Math.abs(totals.total_put_oi_chg) / chgMax * 100) + '%';

        // Total Sidebar
        document.getElementById('totalCallOi').textContent = format(totals.total_call_oi);
        document.getElementById('totalPutOi').textContent = format(totals.total_put_oi);

        const totalMax = Math.max(totals.total_call_oi, totals.total_put_oi, 1);
        document.getElementById('callTotalBar').style.width = (totals.total_call_oi / totalMax * 100) + '%';
        document.getElementById('putTotalBar').style.width = (totals.total_put_oi / totalMax * 100) + '%';
    }

    renderPCRGauge(data) {
        const gaugeCtx = document.getElementById('pcrGauge')?.getContext('2d');
        const trendCtx = document.getElementById('pcrTrendSparkline')?.getContext('2d');
        if (!gaugeCtx) return;

        if (this.charts.pcrGauge) this.charts.pcrGauge.destroy();
        if (this.charts.pcrSparkline) this.charts.pcrSparkline.destroy();

        const history = (data.history || data || []);
        const pcr = history.length > 0 ? history[history.length - 1].pcr_oi : 0;

        // Sparkline
        if (trendCtx) {
            this.charts.pcrSparkline = new Chart(trendCtx, {
                type: 'line',
                data: {
                    labels: history.map((_, i) => i),
                    datasets: [{
                        data: history.map(h => h.pcr_oi),
                        borderColor: '#3b82f6',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: true,
                        backgroundColor: 'rgba(59, 130, 246, 0.05)'
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    scales: { x: { display: false }, y: { display: false } },
                    plugins: { legend: { display: false } }
                }
            });
        }

        this.charts.pcrGauge = new Chart(gaugeCtx, {
            type: 'doughnut',
            data: {
                datasets: [{
                    data: [0.7, 0.4, 0.9],
                    backgroundColor: ['rgba(255, 51, 102, 0.2)', 'rgba(71, 85, 105, 0.2)', 'rgba(0, 255, 194, 0.2)'],
                    borderWidth: 0,
                    needleValue: pcr
                }]
            },
            options: {
                circumference: 180, rotation: 270, cutout: '80%', aspectRatio: 2,
                plugins: { legend: { display: false }, tooltip: { enabled: false } }
            },
            plugins: [{
                id: 'needle',
                afterDraw: (chart) => {
                    const { ctx, chartArea } = chart;
                    if (!chartArea || !chart._metasets[0]) return;
                    ctx.save();
                    const needleValue = chart.config.data.datasets[0].needleValue;
                    const angle = Math.PI + (Math.min(Math.max(needleValue, 0), 2) / 2) * Math.PI;
                    const cx = chartArea.width / 2, cy = chart._metasets[0].data[0].y;
                    ctx.translate(cx, cy); ctx.rotate(angle);
                    ctx.beginPath(); ctx.moveTo(0, -1); ctx.lineTo(chartArea.height * 0.8, 0); ctx.lineTo(0, 1);
                    ctx.fillStyle = this.theme === 'light' ? '#0f172a' : '#fff'; ctx.fill();
                    ctx.restore();
                }
            }]
        });

        const sig = document.getElementById('pcrSignal');
        if (sig) {
            sig.textContent = pcr > 1.1 ? 'BULLISH' : pcr < 0.7 ? 'BEARISH' : 'NEUTRAL';
            sig.className = `text-[8px] font-black px-1.5 py-0.5 rounded uppercase ${pcr > 1.1 ? 'bg-green-500/20 text-green-500' : pcr < 0.7 ? 'bg-red-500/20 text-red-500' : 'bg-gray-500/20 text-gray-400'}`;
        }
    }

    // Removed old charts implementations

    renderSupportResistance(data) {
        const container = document.getElementById('supportResistance');
        if (!container) return;
        container.innerHTML = '';
        const all = [...(data.resistance_levels || []).map(l => ({...l, type: 'RES'})), ...(data.support_levels || []).map(l => ({...l, type: 'SUP'}))].sort((a,b) => b.strike - a.strike);

        all.forEach(l => {
            const isSup = l.type === 'SUP';
            const color = isSup ? 'text-green-500' : 'text-red-500';
            const div = document.createElement('div');
            div.className = `flex justify-between items-center p-2 ${isSup ? 'bg-green-500/5 border-green-500/20' : 'bg-red-500/5 border-red-500/20'} border-l-4 rounded mb-1`;
            div.innerHTML = `<div><span class="text-xs font-black ${color}">${l.strike}</span> <span class="text-[8px] text-gray-500 uppercase">${l.type}</span></div><div class="text-[10px] font-bold">${(l.oi/1000000).toFixed(2)}M</div>`;
            container.appendChild(div);
        });
    }

    updateSummaryFromOverview(data) {
        const history = (data.history || data || []);
        if (history.length === 0) return;
        const last = history[history.length - 1];
        document.getElementById('pcrValue').textContent = last.pcr_oi?.toFixed(2) || '0.00';
        document.getElementById('pcrVol').textContent = last.pcr_vol?.toFixed(2) || '-';
        document.getElementById('pcrOiChg').textContent = last.pcr_oi_change?.toFixed(2) || '-';
        document.getElementById('maxPain').textContent = (last.max_pain || 0).toLocaleString();
    }

    switchTab(tabId) {
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.toggle('tab-active', btn.dataset.tab === tabId));
        document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.toggle('hidden', pane.id !== `${tabId}Tab`));
    }

    async triggerBackfill() {
        const res = await fetch('/api/options/backfill', { method: 'POST' }).then(r => r.json());
        alert(res.message);
    }

    toggleTheme() {
        this.theme = this.theme === 'light' ? 'dark' : 'light';
        localStorage.setItem('theme', this.theme);
        this.applyTheme(this.theme);
        // Re-render charts to update colors
        this.loadData();
    }

    applyTheme(theme) {
        document.body.classList.toggle('light-theme', theme === 'light');
        if (theme === 'light') {
            document.getElementById('optionsSunIcon')?.classList.add('hidden');
            document.getElementById('optionsMoonIcon')?.classList.remove('hidden');
        } else {
            document.getElementById('optionsSunIcon')?.classList.remove('hidden');
            document.getElementById('optionsMoonIcon')?.classList.add('hidden');
        }
    }

    // Scalper UI
    renderScalperMetrics(data) {
        document.getElementById('scalperOIPower').textContent = data.oi_power;
        const sentEl = document.getElementById('scalperOISentiment');
        sentEl.textContent = data.oi_sentiment.replace(/_/g, ' ');
        sentEl.className = `text-lg font-black mt-1 ${data.oi_sentiment.includes('BULLISH') ? 'text-green-500' : 'text-red-500'}`;

        if (data.confluence) {
            const update = (id, val) => document.getElementById(id)?.classList.toggle('opacity-40', !val);
            update('conf-lvl', data.confluence.lvl);
            update('conf-pcr', data.confluence.pcr);
            update('conf-oi', data.confluence.oi);
            update('conf-brk', data.confluence.opt_brk);
            update('conf-inv', data.confluence.inv_dwn);
        }
    }

    renderScalperLog(data) {
        const logEl = document.getElementById('scalperLog');
        if (!logEl) return;
        const p = document.createElement('p');
        p.textContent = data.message || `[${data.time}] ${data.signal} @ ${data.underlying_level}`;
        p.className = p.textContent.includes('BUY') ? 'text-green-400 font-bold' : 'text-gray-300';
        logEl.prepend(p);
        if (logEl.children.length > 50) logEl.lastChild.remove();
    }

    async updateScalperStatusUI() {
        const data = await fetch('/api/scalper/status').then(r => r.json());
        const active = data.is_running;
        document.getElementById('statusDot').className = `w-2 h-2 rounded-full ${active ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500'}`;
        document.getElementById('statusText').textContent = active ? 'Active: ' + data.underlying : 'Inactive';
        document.getElementById('startScalperBtn').classList.toggle('hidden', active);
        document.getElementById('stopScalperBtn').classList.toggle('hidden', !active);
    }

    async startScalper() {
        await fetch(`/api/scalper/start?underlying=${document.getElementById('scalperUnderlying').value}`, { method: 'POST' });
        this.updateScalperStatusUI();
    }

    async stopScalper() {
        await fetch('/api/scalper/stop', { method: 'POST' });
        this.updateScalperStatusUI();
    }

    // Strategy Builder
    addLeg() {
        const list = document.getElementById('legsList');
        const div = document.createElement('div');
        div.className = 'flex gap-2 items-center bg-black/20 p-2 rounded leg-item';
        div.innerHTML = `
            <input type="number" placeholder="Strike" class="leg-strike bg-slate-800 border-none text-[10px] w-20 rounded p-1">
            <select class="leg-type bg-slate-800 border-none text-[10px] rounded p-1">
                <option value="call">CE</option><option value="put">PE</option>
            </select>
            <select class="leg-pos bg-slate-800 border-none text-[10px] rounded p-1">
                <option value="long">Buy</option><option value="short">Sell</option>
            </select>
            <input type="number" placeholder="Prem" class="leg-prem bg-slate-800 border-none text-[10px] w-16 rounded p-1">
            <button class="text-red-500 hover:text-red-400 p-1" onclick="this.parentElement.remove()">×</button>
        `;
        list.appendChild(div);
    }

    async buildStrategy() {
        const type = document.getElementById('strategyType').value;
        const payload = {
            underlying: this.currentUnderlying,
            strategy_type: type,
            legs: []
        };

        if (type === 'custom') {
            document.querySelectorAll('.leg-item').forEach(leg => {
                payload.legs.push({
                    strike: parseFloat(leg.querySelector('.leg-strike').value),
                    option_type: leg.querySelector('.leg-type').value,
                    position: leg.querySelector('.leg-pos').value,
                    premium: parseFloat(leg.querySelector('.leg-prem').value),
                    expiry: '2026-12-31' // Simplified for refactor
                });
            });
        }

        try {
            const res = await fetch('/api/options/strategy/build', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(r => r.json());

            this.renderStrategyAnalysis(res);
        } catch (e) { alert("Failed to build strategy"); }
    }

    renderStrategyAnalysis(data) {
        const container = document.getElementById('strategyAnalysis');
        if (!container) return;

        container.innerHTML = `
            <div class="grid grid-cols-2 gap-4 mb-4">
                <div class="p-3 bg-black/10 rounded">
                    <div class="text-[8px] text-gray-500 uppercase">Max Profit</div>
                    <div class="text-sm font-black text-green-500">${data.max_profit}</div>
                </div>
                <div class="p-3 bg-black/10 rounded">
                    <div class="text-[8px] text-gray-500 uppercase">Max Loss</div>
                    <div class="text-sm font-black text-red-500">${data.max_loss}</div>
                </div>
            </div>
            <div class="text-[10px] text-gray-400 mb-2 uppercase font-bold">Breakeven Points: ${data.breakeven_points.join(', ') || 'N/A'}</div>
            <div class="grid grid-cols-4 gap-2 text-center">
                <div class="p-1 bg-blue-500/5 rounded"><div class="text-[7px] text-gray-500">Delta</div><div class="text-xs font-bold">${data.net_delta}</div></div>
                <div class="p-1 bg-orange-500/5 rounded"><div class="text-[7px] text-gray-500">Theta</div><div class="text-xs font-bold">${data.net_theta}</div></div>
                <div class="p-1 bg-purple-500/5 rounded"><div class="text-[7px] text-gray-500">Vega</div><div class="text-xs font-bold">${data.net_vega}</div></div>
                <div class="p-1 bg-green-500/5 rounded"><div class="text-[7px] text-gray-500">Gamma</div><div class="text-xs font-bold">${data.net_gamma}</div></div>
            </div>
        `;

        if (data.payoff_chart_data) this.renderPayoffChart(data.payoff_chart_data);
    }

    renderPayoffChart(data) {
        const ctx = document.getElementById('payoffChart')?.getContext('2d');
        if (!ctx) return;
        document.getElementById('payoffChartContainer').classList.remove('hidden');
        if (this.charts.payoff) this.charts.payoff.destroy();

        this.charts.payoff = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.prices,
                datasets: [{
                    label: 'P&L at Expiry',
                    data: data.pnl,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { grid: { color: 'rgba(255,255,255,0.05)' } },
                    y: { grid: { color: 'rgba(255,255,255,0.1)' } }
                }
            }
        });
    }

    // Alerts Management
    async createAlert() {
        const payload = {
            name: document.getElementById('alertName').value,
            underlying: this.currentUnderlying,
            alert_type: document.getElementById('alertType').value,
            threshold: parseFloat(document.getElementById('alertThreshold').value)
        };

        await fetch('/api/alerts/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        this.loadAlerts();
    }

    async loadAlerts() {
        const alerts = await fetch(`/api/alerts/list/${this.currentUnderlying}`).then(r => r.json());
        this.renderAlerts(alerts);
    }

    renderAlerts(alerts) {
        const container = document.getElementById('alertsList');
        if (!container) return;
        container.innerHTML = '';

        if (alerts.length === 0) {
            container.innerHTML = '<p class="text-gray-500 text-xs italic">No active alerts for this underlying.</p>';
            return;
        }

        alerts.forEach(alert => {
            const div = document.createElement('div');
            div.className = 'flex justify-between items-center p-3 glass-panel rounded border-l-4 border-purple-500 mb-2';
            div.innerHTML = `
                <div>
                    <div class="text-xs font-bold">${alert.name}</div>
                    <div class="text-[9px] text-gray-500 uppercase">${alert.alert_type.replace('_', ' ')} @ ${alert.threshold}</div>
                </div>
                <div class="flex gap-2">
                    <button class="p-1 hover:text-blue-500" onclick="window.optionsDashboard.toggleAlert('${alert.id}')">
                        ${alert.is_active ? '⏸' : '▶'}
                    </button>
                    <button class="p-1 hover:text-red-500" onclick="window.optionsDashboard.deleteAlert('${alert.id}')">🗑</button>
                </div>
            `;
            container.appendChild(div);
        });
    }

    async toggleAlert(id) {
        await fetch(`/api/alerts/toggle/${id}`, { method: 'POST' });
        this.loadAlerts();
    }

    async deleteAlert(id) {
        if (confirm("Delete this alert?")) {
            await fetch(`/api/alerts/delete/${id}`, { method: 'DELETE' });
            this.loadAlerts();
        }
    }
}

// Bootstrap
document.addEventListener('DOMContentLoaded', () => {
    window.optionsDashboard = new OptionsDashboardManager();
});
