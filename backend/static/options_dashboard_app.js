/**
 * PRODESK Options Dashboard v4.0 - Side-by-Side Edition
 * Unified management of NIFTY & BANKNIFTY Analysis.
 */

class OptionsDashboardManager {
    constructor() {
        this.underlyings = ['NSE:NIFTY', 'NSE:BANKNIFTY'];
        this.socket = null;
        this.charts = {};
        this.theme = localStorage.getItem('theme') || 'dark';

        this.colors = {
            ce: '#ef4444', // red-500
            pe: '#10b981', // emerald-500
            spot: '#94a3b8',
            diff: '#3b82f6'  // blue-500
        };

        // Chart.js defaults for miniature display
        if (window.Chart) {
            Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";
            Chart.defaults.color = '#94a3b8';
            Chart.defaults.font.size = 7;
        }

        this.init();
    }

    async init() {
        this.applyTheme(this.theme);
        this.initSocket();
        this.setupEventListeners();
        await this.loadAllData();

        // Auto-refresh every 2 minutes
        setInterval(() => this.loadAllData(), 120000);
    }

    initSocket() {
        this.socket = io();
        this.socket.on('connect', () => {
            console.log("[Options] Socket connected");
            this.underlyings.forEach(u => {
                this.socket.emit('subscribe_options', { underlying: u });
                this.socket.emit('subscribe', { instrumentKeys: [u], interval: '1' });
            });
        });

        this.socket.on('raw_tick', (data) => {
            this.underlyings.forEach(u => {
                if (data[u]) {
                    const prefix = u.includes('BANK') ? 'banknifty' : 'nifty';
                    const price = parseFloat(data[u].last_price);
                    if (price > 0) {
                        const el = document.getElementById(`${prefix}_spotPrice`);
                        if (el) el.textContent = price.toLocaleString(undefined, {minimumFractionDigits: 2});
                    }
                }
            });
        });

        this.socket.on('chart_update', (data) => {
            this.underlyings.forEach(u => {
                if (data.instrumentKey === u && data.ohlcv?.length > 0) {
                    const prefix = u.includes('BANK') ? 'banknifty' : 'nifty';
                    const price = parseFloat(data.ohlcv[data.ohlcv.length - 1][4]);
                    if (price > 0) {
                        const el = document.getElementById(`${prefix}_spotPrice`);
                        if (el) el.textContent = price.toLocaleString(undefined, {minimumFractionDigits: 2});
                    }
                }
            });
        });
    }

    setupEventListeners() {
        document.getElementById('refreshBtn').addEventListener('click', () => this.loadAllData());
        document.getElementById('backfillBtn').addEventListener('click', () => this.triggerBackfill());
        document.getElementById('optionsThemeToggle').addEventListener('click', () => this.toggleTheme());
    }

    async loadAllData() {
        try {
            await Promise.all(this.underlyings.map(u => this.loadDataForUnderlying(u)));
            document.getElementById('lastUpdated').textContent = new Date().toLocaleTimeString('en-IN', { hour12: false });
        } catch (e) { console.error("[Options] Load all failed:", e); }
    }

    async loadDataForUnderlying(u) {
        const prefix = u.includes('BANK') ? 'banknifty' : 'nifty';
        try {
            const [genie, detailedTrend, oiAnalysis, pcrTrend] = await Promise.all([
                fetch(`/api/options/genie-insights/${u}`).then(r => r.json()),
                fetch(`/api/options/oi-trend-detailed/${u}`).then(r => r.json()),
                fetch(`/api/options/oi-analysis/${u}`).then(r => r.json()),
                fetch(`/api/options/pcr-trend/${u}`).then(r => r.json())
            ]);

            this.renderGenieCard(prefix, genie);
            this.renderCEvsPEChangeChart(prefix, detailedTrend);
            this.renderOIDiffChart(prefix, detailedTrend);
            this.renderStrikeWiseCharts(prefix, oiAnalysis);
            this.renderPCRTrend(prefix, pcrTrend);
        } catch (e) { console.error(`[Options] Load failed for ${u}:`, e); }
    }

    renderGenieCard(prefix, data) {
        const el = document.getElementById(`${prefix}_genieControl`);
        if (!el) return;
        el.textContent = data.control.replace(/_/g, ' ');
        el.className = `text-[10px] font-black uppercase ${data.control.includes('BUYERS') ? 'text-green-500' : data.control.includes('SELLERS') ? 'text-red-500' : 'text-white'}`;

        const distEl = document.getElementById(`${prefix}_genieDistribution`);
        if (distEl) distEl.textContent = data.distribution.status;

        const rangeEl = document.getElementById(`${prefix}_genieRange`);
        if (rangeEl) rangeEl.textContent = `${data.boundaries.lower} - ${data.boundaries.upper}`;

        const mpEl = document.getElementById(`${prefix}_maxPain`);
        if (mpEl) mpEl.textContent = data.max_pain.toLocaleString();
    }

    renderCEvsPEChangeChart(prefix, data) {
        const chartId = `${prefix}_ceVsPe`;
        const ctx = document.getElementById(`${prefix}_ceVsPeChangeChart`)?.getContext('2d');
        if (!ctx) return;
        if (this.charts[chartId]) this.charts[chartId].destroy();

        const history = data.history || [];
        const labels = history.map(h => new Date(h.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }));

        this.charts[chartId] = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'CE', data: history.map(h => h.ce_oi_change), borderColor: this.colors.ce, borderWidth: 1, pointRadius: 0, fill: false, tension: 0.3, yAxisID: 'y' },
                    { label: 'PE', data: history.map(h => h.pe_oi_change), borderColor: this.colors.pe, borderWidth: 1, pointRadius: 0, fill: false, tension: 0.3, yAxisID: 'y' },
                    { label: 'Spot', data: history.map(h => h.spot_price), borderColor: this.theme === 'light' ? '#f59e0b' : '#fff', borderDash: [2, 2], borderWidth: 0.5, pointRadius: 0, yAxisID: 'y1' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: true, position: 'top', labels: { boxWidth: 4, font: { size: 6 } } } },
                scales: {
                    x: { ticks: { autoSkip: true, maxTicksLimit: 4, font: { size: 6 } }, grid: { display: false } },
                    y: { position: 'left', ticks: { font: { size: 6 }, callback: v => (v/1000000).toFixed(1)+'M' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                    y1: { position: 'right', ticks: { font: { size: 6 } }, grid: { display: false } }
                }
            }
        });
    }

    renderPCRTrend(prefix, data) {
        const chartId = `${prefix}_pcrTrend`;
        const ctx = document.getElementById(`${prefix}_pcrTrendChart`)?.getContext('2d');
        if (!ctx) return;
        if (this.charts[chartId]) this.charts[chartId].destroy();

        const history = data.history || [];
        if (history.length === 0) return;

        const lastValue = history[history.length - 1].pcr_oi;
        const pcrEl = document.getElementById(`${prefix}_currentPcrValue`);
        if (pcrEl) {
            pcrEl.textContent = lastValue.toFixed(2);
            pcrEl.className = `mini-text font-black ${lastValue > 1 ? 'text-green-500' : lastValue < 0.7 ? 'text-red-500' : 'text-blue-500'}`;
        }

        this.charts[chartId] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: history.map((_, i) => i),
                datasets: [{
                    data: history.map(h => h.pcr_oi),
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { x: { display: false }, y: { display: false } }
            }
        });
    }

    renderOIDiffChart(prefix, data) {
        const chartId = `${prefix}_oiDiff`;
        const ctx = document.getElementById(`${prefix}_oiDiffChart`)?.getContext('2d');
        if (!ctx) return;
        if (this.charts[chartId]) this.charts[chartId].destroy();

        const history = data.history || [];
        const labels = history.map(h => new Date(h.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }));

        this.charts[chartId] = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'Diff', data: history.map(h => h.pe_oi_change - h.ce_oi_change), borderColor: this.colors.diff, backgroundColor: this.colors.diff + '1A', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1, yAxisID: 'y' },
                    { label: 'Spot', data: history.map(h => h.spot_price), borderColor: this.theme === 'light' ? '#f59e0b' : '#fff', borderDash: [2, 2], borderWidth: 0.5, pointRadius: 0, yAxisID: 'y1' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { autoSkip: true, maxTicksLimit: 4, font: { size: 6 } }, grid: { display: false } },
                    y: { ticks: { font: { size: 6 }, callback: v => (v/1000000).toFixed(1)+'M' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                    y1: { position: 'right', ticks: { font: { size: 6 } }, grid: { display: false } }
                }
            }
        });
    }

    renderStrikeWiseCharts(prefix, data) {
        this.renderStrikeWiseOiChange(prefix, data);
        this.renderStrikeWiseTotalOi(prefix, data);
        this.updateStats(prefix, data.totals);
    }

    renderStrikeWiseOiChange(prefix, data) {
        const chartId = `${prefix}_strikeOiChg`;
        const ctx = document.getElementById(`${prefix}_strikeWiseOiChangeChart`)?.getContext('2d');
        if (!ctx) return;
        if (this.charts[chartId]) this.charts[chartId].destroy();

        const oiData = data.data || [];
        this.charts[chartId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: oiData.map(d => d.strike),
                datasets: [
                    { label: 'CE', data: oiData.map(d => d.call_oi_change), backgroundColor: this.colors.ce + 'B3' },
                    { label: 'PE', data: oiData.map(d => d.put_oi_change), backgroundColor: this.colors.pe + 'B3' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 5 }, maxRotation: 90 } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 6 }, callback: v => (v/1000000).toFixed(1)+'M' } }
                }
            }
        });
    }

    renderStrikeWiseTotalOi(prefix, data) {
        const chartId = `${prefix}_strikeTotalOi`;
        const ctx = document.getElementById(`${prefix}_strikeWiseTotalOiChart`)?.getContext('2d');
        if (!ctx) return;
        if (this.charts[chartId]) this.charts[chartId].destroy();

        const oiData = data.data || [];
        this.charts[chartId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: oiData.map(d => d.strike),
                datasets: [
                    { label: 'CE', data: oiData.map(d => d.call_oi), backgroundColor: this.colors.ce + 'B3' },
                    { label: 'PE', data: oiData.map(d => d.put_oi), backgroundColor: this.colors.pe + 'B3' }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 5 }, maxRotation: 90 } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { font: { size: 6 }, callback: v => (v/1000000).toFixed(1)+'M' } }
                }
            }
        });
    }

    updateStats(prefix, totals) {
        if (!totals) return;
        const format = (v) => {
            if (Math.abs(v) >= 10000000) return (v / 10000000).toFixed(1) + 'Cr';
            if (Math.abs(v) >= 100000) return (v / 100000).toFixed(1) + 'L';
            return v;
        };
        document.getElementById(`${prefix}_totalCallOiChg`).textContent = format(totals.total_call_oi_chg);
        document.getElementById(`${prefix}_totalPutOiChg`).textContent = format(totals.total_put_oi_chg);
        document.getElementById(`${prefix}_totalCallOi`).textContent = format(totals.total_call_oi);
        document.getElementById(`${prefix}_totalPutOi`).textContent = format(totals.total_put_oi);
    }

    async triggerBackfill() {
        const res = await fetch('/api/options/backfill', { method: 'POST' }).then(r => r.json());
        alert(res.message);
    }

    toggleTheme() {
        this.theme = this.theme === 'light' ? 'dark' : 'light';
        localStorage.setItem('theme', this.theme);
        this.applyTheme(this.theme);
        this.loadAllData();
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
}

document.addEventListener('DOMContentLoaded', () => {
    window.optionsDashboard = new OptionsDashboardManager();
});
