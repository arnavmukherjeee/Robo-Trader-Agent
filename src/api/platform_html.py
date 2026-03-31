"""Full trading platform dashboard — backtesting, live data, strategy analytics."""

PLATFORM_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Robo-Trader | AI Strategy Platform</title>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#0a0a0f;--surface:#111118;--surface2:#1a1a24;--surface3:#22222e;
    --border:#2a2a3a;--border2:#363648;
    --text:#e8e8f0;--text2:#8888a0;--text3:#555568;
    --green:#00e676;--green2:#00c853;--red:#ff5252;--red2:#d32f2f;
    --blue:#448aff;--blue2:#2962ff;--purple:#b388ff;--amber:#ffd740;
    --cyan:#18ffff;--orange:#ff9100;
    --radius:12px;--radius-sm:8px;
  }
  html{font-size:14px;scroll-behavior:smooth}
  body{
    font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    background:var(--bg);color:var(--text);min-height:100vh;
  }
  a{color:var(--blue);text-decoration:none}
  ::-webkit-scrollbar{width:6px;height:6px}
  ::-webkit-scrollbar-track{background:transparent}
  ::-webkit-scrollbar-thumb{background:#333;border-radius:3px}

  /* ── Nav ──────────────────────── */
  .nav{
    display:flex;align-items:center;justify-content:space-between;
    padding:14px 32px;background:var(--surface);
    border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100;
    backdrop-filter:blur(12px);
  }
  .nav-left{display:flex;align-items:center;gap:20px}
  .logo{font-size:1.4rem;font-weight:800;letter-spacing:-.5px}
  .logo span{background:linear-gradient(135deg,var(--green),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
  .nav-tabs{display:flex;gap:4px;background:var(--surface2);border-radius:8px;padding:3px}
  .nav-tab{
    padding:7px 18px;border-radius:6px;font-size:.82rem;font-weight:600;
    cursor:pointer;color:var(--text2);transition:all .2s;border:none;background:none;
  }
  .nav-tab:hover{color:var(--text)}
  .nav-tab.active{background:var(--surface3);color:var(--text);box-shadow:0 1px 4px rgba(0,0,0,.3)}
  .nav-right{display:flex;align-items:center;gap:14px}
  .live-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:blink 2s infinite}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
  .equity-display{font-size:1rem;font-weight:700;font-family:'SF Mono',monospace}

  /* ── Layout ──────────────────── */
  .container{padding:20px 32px;max-width:1800px;margin:0 auto}
  .page{display:none}
  .page.active{display:block}

  /* ── Cards Grid ──────────────── */
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}
  .card{
    background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    padding:16px 18px;transition:all .2s;
  }
  .card:hover{border-color:var(--border2);transform:translateY(-1px)}
  .card-label{font-size:.7rem;text-transform:uppercase;letter-spacing:1.2px;color:var(--text2);margin-bottom:6px}
  .card-value{font-size:1.5rem;font-weight:700;font-family:'SF Mono',Consolas,monospace}
  .card-sub{font-size:.72rem;color:var(--text3);margin-top:4px}
  .positive{color:var(--green)}
  .negative{color:var(--red)}
  .neutral{color:var(--text2)}

  /* ── Panel ───────────────────── */
  .panel{
    background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    margin-bottom:20px;overflow:hidden;
  }
  .panel-header{
    display:flex;align-items:center;justify-content:space-between;
    padding:14px 20px;border-bottom:1px solid var(--border);
  }
  .panel-title{font-size:.95rem;font-weight:700;display:flex;align-items:center;gap:10px}
  .panel-body{padding:16px 20px}
  .badge{
    background:var(--surface2);border:1px solid var(--border);
    border-radius:12px;padding:2px 10px;font-size:.72rem;color:var(--text2);
  }
  .badge-green{background:rgba(0,230,118,.1);border-color:rgba(0,230,118,.3);color:var(--green)}
  .badge-red{background:rgba(255,82,82,.1);border-color:rgba(255,82,82,.3);color:var(--red)}

  /* ── Chart Container ─────────── */
  .chart-wrap{height:400px;position:relative;background:var(--bg);border-radius:var(--radius-sm)}
  .chart-wrap.small{height:200px}

  /* ── Tables ──────────────────── */
  table{width:100%;border-collapse:collapse}
  th{
    text-align:left;padding:10px 14px;font-size:.7rem;text-transform:uppercase;
    letter-spacing:.8px;color:var(--text2);background:var(--surface2);
    border-bottom:1px solid var(--border);position:sticky;top:0;
  }
  td{padding:10px 14px;font-size:.84rem;border-bottom:1px solid var(--border)}
  tr:hover td{background:rgba(255,255,255,.015)}
  .mono{font-family:'SF Mono',Consolas,monospace}
  .text-right{text-align:right}
  .table-scroll{max-height:500px;overflow-y:auto}

  /* ── Strategy Row ────────────── */
  .strat-rank{
    width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    font-size:.72rem;font-weight:700;
  }
  .rank-gold{background:linear-gradient(135deg,#ffd740,#ff9100);color:#000}
  .rank-silver{background:linear-gradient(135deg,#e0e0e0,#9e9e9e);color:#000}
  .rank-bronze{background:linear-gradient(135deg,#ffab91,#ff6e40);color:#000}
  .rank-default{background:var(--surface3);color:var(--text2)}

  /* ── Metric Bars ─────────────── */
  .metric-bar{height:6px;border-radius:3px;background:var(--surface3);overflow:hidden;width:80px;display:inline-block;vertical-align:middle;margin-left:6px}
  .metric-bar-fill{height:100%;border-radius:3px;transition:width .5s}
  .bar-green{background:linear-gradient(90deg,var(--green2),var(--green))}
  .bar-red{background:linear-gradient(90deg,var(--red2),var(--red))}
  .bar-blue{background:linear-gradient(90deg,var(--blue2),var(--blue))}

  /* ── Controls ────────────────── */
  .controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
  select,input[type=text]{
    background:var(--surface2);border:1px solid var(--border);border-radius:6px;
    padding:8px 14px;color:var(--text);font-size:.84rem;outline:none;
  }
  select:focus,input:focus{border-color:var(--blue)}
  .btn{
    padding:8px 20px;border:none;border-radius:6px;font-size:.84rem;
    font-weight:600;cursor:pointer;transition:all .15s;
  }
  .btn:active{transform:scale(.96)}
  .btn-primary{background:var(--blue);color:#fff}
  .btn-primary:hover{background:var(--blue2)}
  .btn-green{background:var(--green);color:#000}
  .btn-green:hover{background:var(--green2)}
  .btn-red{background:var(--red);color:#fff}
  .btn-red:hover{background:var(--red2)}
  .btn-outline{background:none;border:1px solid var(--border);color:var(--text2)}
  .btn-outline:hover{border-color:var(--text2);color:var(--text)}
  .btn:disabled{opacity:.4;cursor:not-allowed}

  /* ── Loading ─────────────────── */
  .spinner{width:20px;height:20px;border:2px solid var(--border);border-top-color:var(--blue);border-radius:50%;animation:spin .8s linear infinite;display:inline-block}
  @keyframes spin{to{transform:rotate(360deg)}}
  .loading-overlay{
    position:absolute;inset:0;background:rgba(10,10,15,.8);display:flex;
    align-items:center;justify-content:center;flex-direction:column;gap:12px;
    font-size:.9rem;color:var(--text2);z-index:10;border-radius:var(--radius);
  }

  /* ── Grid Layouts ────────────── */
  .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
  .grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px}
  @media(max-width:1100px){.grid-2,.grid-3{grid-template-columns:1fr}}

  /* ── Ticker Strip ────────────── */
  .ticker-strip{
    display:flex;gap:16px;padding:10px 20px;overflow-x:auto;
    background:var(--surface);border-bottom:1px solid var(--border);
  }
  .ticker-item{
    display:flex;align-items:center;gap:8px;padding:6px 12px;
    background:var(--surface2);border-radius:6px;white-space:nowrap;min-width:fit-content;
  }
  .ticker-sym{font-weight:700;font-size:.82rem}
  .ticker-price{font-family:'SF Mono',monospace;font-size:.82rem}
  .ticker-chg{font-size:.75rem;font-weight:600;padding:2px 6px;border-radius:4px}
  .ticker-chg.up{background:rgba(0,230,118,.1);color:var(--green)}
  .ticker-chg.down{background:rgba(255,82,82,.1);color:var(--red)}

  /* ── P&L Chart ───────────────── */
  .pnl-canvas-wrap{height:180px;padding:10px}
  .pnl-canvas-wrap canvas{width:100%!important;height:100%!important}

  /* ── Responsive ──────────────── */
  @media(max-width:768px){
    .nav{padding:10px 16px;flex-wrap:wrap;gap:10px}
    .container{padding:14px 16px}
    .cards{grid-template-columns:repeat(2,1fr)}
  }
</style>
</head>
<body>

<!-- Nav -->
<nav class="nav">
  <div class="nav-left">
    <div class="logo">Robo<span>Trader</span> <span style="font-size:.7rem;color:var(--text3)">AI</span></div>
    <div class="nav-tabs">
      <button class="nav-tab active" onclick="switchPage('overview')">Overview</button>
      <button class="nav-tab" onclick="switchPage('backtest')">Backtest</button>
      <button class="nav-tab" onclick="switchPage('live')">Live Trading</button>
      <button class="nav-tab" onclick="switchPage('strategies')">Strategies</button>
    </div>
  </div>
  <div class="nav-right">
    <div class="live-dot" id="liveDot"></div>
    <div class="equity-display" id="navEquity">$--</div>
  </div>
</nav>

<!-- Ticker Strip -->
<div class="ticker-strip" id="tickerStrip">
  <div class="ticker-item"><span class="ticker-sym">Loading...</span></div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE: Overview -->
<!-- ═══════════════════════════════════════════ -->
<div class="page active" id="page-overview">
<div class="container">
  <div class="cards">
    <div class="card">
      <div class="card-label">Portfolio Value</div>
      <div class="card-value" id="ov-equity">$--</div>
      <div class="card-sub" id="ov-equity-sub">--</div>
    </div>
    <div class="card">
      <div class="card-label">Cash Available</div>
      <div class="card-value" id="ov-cash">$--</div>
      <div class="card-sub" id="ov-buying-power">Buying power: --</div>
    </div>
    <div class="card">
      <div class="card-label">Today's P&L</div>
      <div class="card-value" id="ov-pnl">$--</div>
      <div class="card-sub" id="ov-pnl-sub">--</div>
    </div>
    <div class="card">
      <div class="card-label">Win Rate</div>
      <div class="card-value" id="ov-winrate">--%</div>
      <div class="card-sub" id="ov-winrate-sub">--</div>
    </div>
    <div class="card">
      <div class="card-label">Total Trades</div>
      <div class="card-value" id="ov-trades">--</div>
      <div class="card-sub" id="ov-trades-sub">--</div>
    </div>
    <div class="card">
      <div class="card-label">Open Positions</div>
      <div class="card-value" id="ov-positions">0</div>
      <div class="card-sub" id="ov-positions-sub">--</div>
    </div>
  </div>

  <div class="grid-2">
    <!-- Portfolio Chart -->
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">BTC/USD</div>
        <span class="badge" id="btc-price-badge">--</span>
      </div>
      <div class="chart-wrap" id="btcChart"></div>
    </div>
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">ETH/USD</div>
        <span class="badge" id="eth-price-badge">--</span>
      </div>
      <div class="chart-wrap" id="ethChart"></div>
    </div>
  </div>

  <!-- Autopilot Status -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">🤖 Autopilot <span class="badge badge-green" id="ap-phase">STARTING</span></div>
      <div style="font-size:.75rem;color:var(--text3)" id="ap-meta">--</div>
    </div>
    <div class="panel-body" style="padding:0">
      <div class="grid-3" style="padding:14px 20px;gap:10px">
        <div><span style="color:var(--text3);font-size:.72rem;text-transform:uppercase">Strategies Tested</span><div class="mono" style="font-size:1.2rem;font-weight:700" id="ap-tested">--</div></div>
        <div><span style="color:var(--text3);font-size:.72rem;text-transform:uppercase">Symbols Scanned</span><div class="mono" style="font-size:1.2rem;font-weight:700" id="ap-scanned">--</div></div>
        <div><span style="color:var(--text3);font-size:.72rem;text-transform:uppercase">Active Strategies</span><div class="mono" style="font-size:1.2rem;font-weight:700" id="ap-active">--</div></div>
      </div>
    </div>
  </div>

  <!-- Top Strategies from Autopilot -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Top Strategies (Auto-Selected) <span class="badge" id="ap-strat-count">0</span></div>
    </div>
    <div class="table-scroll" id="apStrategiesTable">
      <div style="padding:30px;text-align:center;color:var(--text3)">Autopilot is researching strategies...</div>
    </div>
  </div>

  <!-- Autopilot Activity Log -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Activity Log</div>
    </div>
    <div style="max-height:200px;overflow-y:auto;padding:12px 16px;font-family:'SF Mono',monospace;font-size:.76rem;line-height:1.7;color:var(--text2);background:#08080e" id="apLog">
      <div style="color:var(--cyan)">Autopilot initializing...</div>
    </div>
  </div>

  <!-- Positions & Trades -->
  <div class="grid-2">
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Open Positions <span class="badge" id="pos-count">0</span></div>
      </div>
      <div class="table-scroll" id="positionsTable">
        <div style="padding:40px;text-align:center;color:var(--text3)">No open positions</div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Closed Trades <span class="badge" id="trade-count">0</span></div>
      </div>
      <div class="table-scroll" id="closedTradesTable">
        <div style="padding:40px;text-align:center;color:var(--text3)">No closed trades</div>
      </div>
    </div>
  </div>
</div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE: Backtest -->
<!-- ═══════════════════════════════════════════ -->
<div class="page" id="page-backtest">
<div class="container">
  <div class="controls">
    <select id="bt-symbol">
      <option value="BTC/USD">BTC/USD</option>
      <option value="ETH/USD">ETH/USD</option>
      <option value="SOL/USD">SOL/USD</option>
      <option value="AAPL">AAPL</option>
      <option value="MSFT">MSFT</option>
      <option value="NVDA">NVDA</option>
      <option value="TSLA">TSLA</option>
      <option value="GOOGL">GOOGL</option>
      <option value="AMZN">AMZN</option>
      <option value="META">META</option>
    </select>
    <select id="bt-days">
      <option value="30">30 days</option>
      <option value="60">60 days</option>
      <option value="90" selected>90 days</option>
      <option value="180">180 days</option>
      <option value="365">1 year</option>
    </select>
    <select id="bt-topn">
      <option value="10">Top 10</option>
      <option value="20" selected>Top 20</option>
      <option value="50">Top 50</option>
    </select>
    <button class="btn btn-primary" id="bt-run" onclick="runBacktest()">Run Backtest</button>
    <span id="bt-status" style="color:var(--text2);font-size:.84rem"></span>
  </div>

  <!-- Backtest Results -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Strategy Performance <span class="badge" id="bt-count">0 strategies</span></div>
    </div>
    <div class="table-scroll" id="backtestResults" style="position:relative;min-height:200px">
      <div style="padding:60px;text-align:center;color:var(--text3)">
        Select a symbol and click "Run Backtest" to evaluate strategies<br>
        <span style="font-size:.75rem;margin-top:8px;display:block">Tests 4.9M+ strategy combinations and finds the top performers</span>
      </div>
    </div>
  </div>
</div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE: Live Trading -->
<!-- ═══════════════════════════════════════════ -->
<div class="page" id="page-live">
<div class="container">
  <div class="controls">
    <button class="btn btn-green" onclick="startScalper()">Start Scalper</button>
    <button class="btn btn-red" onclick="stopScalper()">Stop Scalper</button>
    <button class="btn btn-outline" onclick="closeAll()">Close All Positions</button>
  </div>

  <div class="cards">
    <div class="card">
      <div class="card-label">Scalper Status</div>
      <div class="card-value" id="lv-status" style="font-size:1.1rem">--</div>
    </div>
    <div class="card">
      <div class="card-label">Scalper P&L</div>
      <div class="card-value" id="lv-pnl">$--</div>
    </div>
    <div class="card">
      <div class="card-label">Trades Today</div>
      <div class="card-value" id="lv-trades">--</div>
    </div>
    <div class="card">
      <div class="card-label">Rejected</div>
      <div class="card-value" id="lv-rejected">--</div>
    </div>
  </div>

  <!-- P&L Chart -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Cumulative P&L</div>
    </div>
    <div class="pnl-canvas-wrap"><canvas id="pnlCanvas"></canvas></div>
  </div>

  <!-- Log Feed -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Live Feed</div>
      <span class="badge" id="log-status">Streaming</span>
    </div>
    <div style="height:300px;overflow-y:auto;padding:12px 16px;font-family:'SF Mono',monospace;font-size:.76rem;line-height:1.7;color:var(--text2);background:#08080e" id="logLines">
      <div style="color:var(--cyan)">Waiting for data...</div>
    </div>
  </div>
</div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE: Strategies -->
<!-- ═══════════════════════════════════════════ -->
<div class="page" id="page-strategies">
<div class="container">
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Strategy Leaderboard <span class="badge badge-green" id="strat-count">--</span></div>
    </div>
    <div class="panel-body" style="padding:0">
      <div class="table-scroll" id="leaderboardTable">
        <div style="padding:60px;text-align:center;color:var(--text3)">
          Run backtests first to populate the leaderboard
        </div>
      </div>
    </div>
  </div>
</div>
</div>

<script>
(function(){
  const $ = id => document.getElementById(id);
  let charts = {};

  // ── Page switching ─────────────────
  window.switchPage = function(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    $('page-' + page).classList.add('active');
    event.target.classList.add('active');
    if (page === 'overview' && !charts.btc) initCharts();
  };

  // ── Formatting ─────────────────────
  function fmt(n, d=2) {
    if (n == null || isNaN(n)) return '--';
    return Number(n).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
  }
  function fmtPct(n) { return n == null ? '--' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%'; }
  function cls(n) { return n > 0 ? 'positive' : n < 0 ? 'negative' : 'neutral'; }
  function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  async function fetchJSON(url) {
    try { const r = await fetch(url); return r.ok ? await r.json() : null; } catch { return null; }
  }

  // ── Lightweight Charts ─────────────
  function initCharts() {
    ['btc','eth'].forEach(id => {
      const el = $(id + 'Chart');
      if (!el || charts[id]) return;
      const chart = LightweightCharts.createChart(el, {
        layout: {background:{type:'solid',color:'#0a0a0f'},textColor:'#8888a0',fontSize:11},
        grid: {vertLines:{color:'#1a1a26'},horzLines:{color:'#1a1a26'}},
        crosshair: {mode:0},
        rightPriceScale: {borderColor:'#2a2a3a'},
        timeScale: {borderColor:'#2a2a3a',timeVisible:true},
        handleScroll:true,handleScale:true,
      });
      const series = chart.addCandlestickSeries({
        upColor:'#00e676',downColor:'#ff5252',borderVisible:false,
        wickUpColor:'#00e676',wickDownColor:'#ff5252',
      });
      charts[id] = {chart, series};
      new ResizeObserver(() => chart.applyOptions({width:el.clientWidth,height:el.clientHeight})).observe(el);
    });
    loadCandles('BTC/USD','btc');
    loadCandles('ETH/USD','eth');
  }

  async function loadCandles(symbol, chartId) {
    const data = await fetchJSON('/api/market/candles?symbol=' + encodeURIComponent(symbol) + '&timeframe=1Hour&days=7');
    if (!data || !data.length || !charts[chartId]) return;
    const formatted = data.map(c => ({
      time: Math.floor(new Date(c.t).getTime()/1000),
      open:c.o, high:c.h, low:c.l, close:c.c
    }));
    charts[chartId].series.setData(formatted);
    charts[chartId].chart.timeScale().fitContent();
  }

  // ── Ticker Strip ───────────────────
  async function updateTicker() {
    const data = await fetchJSON('/api/market/prices?symbols=BTC/USD,ETH/USD,SOL/USD,DOGE/USD,AVAX/USD');
    if (!data) return;
    const strip = $('tickerStrip');
    let html = '';
    for (const [sym, info] of Object.entries(data)) {
      const chg = info.change_pct || 0;
      const chgCls = chg >= 0 ? 'up' : 'down';
      html += '<div class="ticker-item">' +
        '<span class="ticker-sym">' + sym + '</span>' +
        '<span class="ticker-price mono">$' + fmt(info.price) + '</span>' +
        '<span class="ticker-chg ' + chgCls + '">' + fmtPct(chg) + '</span></div>';
    }
    strip.innerHTML = html;
  }

  // ── Overview Updates ───────────────
  async function updateOverview() {
    const [acct, stats, positions, trades] = await Promise.all([
      fetchJSON('/account'), fetchJSON('/stats'),
      fetchJSON('/positions'), fetchJSON('/trades/closed')
    ]);

    if (acct) {
      const eq = acct.equity;
      $('ov-equity').textContent = '$' + fmt(eq);
      $('navEquity').textContent = '$' + fmt(eq);
      $('ov-cash').textContent = '$' + fmt(acct.cash);
      $('ov-buying-power').textContent = 'Buying power: $' + fmt(acct.buying_power);
      const dayPnl = eq - 100000;
      $('ov-equity-sub').textContent = (dayPnl >= 0 ? '+' : '') + '$' + fmt(Math.abs(dayPnl)) + ' from start';
      $('ov-equity-sub').className = 'card-sub ' + cls(dayPnl);
    }

    if (stats) {
      const pnl = stats.total_pnl || 0;
      $('ov-pnl').textContent = (pnl >= 0 ? '+' : '-') + '$' + fmt(Math.abs(pnl));
      $('ov-pnl').className = 'card-value ' + cls(pnl);
      $('ov-pnl-sub').textContent = 'W:' + (stats.wins||0) + ' L:' + (stats.losses||0);
      const wr = stats.win_rate;
      $('ov-winrate').textContent = wr != null ? (wr * 100).toFixed(1) + '%' : '--%';
      $('ov-winrate').className = 'card-value ' + (wr >= 0.5 ? 'positive' : wr > 0 ? 'negative' : '');
      $('ov-winrate-sub').textContent = 'Best: $' + fmt(stats.biggest_win||0) + ' / Worst: $' + fmt(Math.abs(stats.biggest_loss||0));
      $('ov-trades').textContent = stats.total_trades || 0;
      $('ov-trades-sub').textContent = 'Rejected: ' + (stats.rejected || 0);
    }

    if (positions) {
      $('ov-positions').textContent = positions.length;
      $('pos-count').textContent = positions.length;
      if (positions.length === 0) {
        $('positionsTable').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text3)">No open positions</div>';
      } else {
        let html = '<table><thead><tr><th>Symbol</th><th class="text-right">Value</th><th class="text-right">P&L</th><th class="text-right">%</th></tr></thead><tbody>';
        let totalPnl = 0;
        for (const p of positions) {
          const pnl = parseFloat(p.unrealized_pl || 0);
          const pct = parseFloat(p.unrealized_plpc || 0) * 100;
          totalPnl += pnl;
          html += '<tr><td><strong>' + p.symbol + '</strong></td>' +
            '<td class="text-right mono">$' + fmt(p.market_value) + '</td>' +
            '<td class="text-right mono ' + cls(pnl) + '">' + (pnl>=0?'+':'') + '$' + fmt(Math.abs(pnl)) + '</td>' +
            '<td class="text-right mono ' + cls(pct) + '">' + fmtPct(pct) + '</td></tr>';
        }
        html += '</tbody></table>';
        $('positionsTable').innerHTML = html;
        $('ov-positions-sub').textContent = 'Unrealized: ' + (totalPnl>=0?'+':'') + '$' + fmt(Math.abs(totalPnl));
        $('ov-positions-sub').className = 'card-sub ' + cls(totalPnl);
      }
    }

    if (trades) {
      $('trade-count').textContent = trades.length;
      if (trades.length === 0) {
        $('closedTradesTable').innerHTML = '<div style="padding:40px;text-align:center;color:var(--text3)">No closed trades</div>';
      } else {
        let html = '<table><thead><tr><th>Symbol</th><th class="text-right">P&L</th><th class="text-right">%</th><th class="text-right">Cumul.</th><th>Time</th></tr></thead><tbody>';
        for (const t of trades.slice(0, 30)) {
          const c = cls(t.pnl);
          const cc = cls(t.cumulative_pnl);
          let time = '--';
          try { time = new Date(t.exit_time).toLocaleTimeString(); } catch {}
          html += '<tr><td><strong>' + t.symbol + '</strong></td>' +
            '<td class="text-right mono ' + c + '">' + (t.pnl>=0?'+':'') + '$' + fmt(Math.abs(t.pnl)) + '</td>' +
            '<td class="text-right mono ' + c + '">' + fmtPct(t.pnl_pct) + '</td>' +
            '<td class="text-right mono ' + cc + '">' + (t.cumulative_pnl>=0?'+':'') + '$' + fmt(Math.abs(t.cumulative_pnl)) + '</td>' +
            '<td class="mono" style="color:var(--text3)">' + time + '</td></tr>';
        }
        html += '</tbody></table>';
        $('closedTradesTable').innerHTML = html;
      }
    }
  }

  // ── Backtest ───────────────────────
  window.runBacktest = async function() {
    const sym = $('bt-symbol').value;
    const days = $('bt-days').value;
    const topn = $('bt-topn').value;
    $('bt-run').disabled = true;
    $('bt-status').innerHTML = '<div class="spinner"></div> Running backtest on ' + sym + '...';
    $('backtestResults').innerHTML = '<div class="loading-overlay"><div class="spinner"></div>Testing strategies on ' + sym + ' (' + days + ' days)...</div>';

    const data = await fetchJSON('/api/backtest/run?symbol=' + encodeURIComponent(sym) + '&days=' + days + '&top_n=' + topn);
    $('bt-run').disabled = false;
    $('bt-status').textContent = '';

    if (!data || !data.length) {
      $('backtestResults').innerHTML = '<div style="padding:40px;text-align:center;color:var(--red)">Backtest failed or no results. Try a different symbol/timeframe.</div>';
      return;
    }

    $('bt-count').textContent = data.length + ' strategies';
    let html = '<table><thead><tr><th>#</th><th>Strategy</th><th class="text-right">Return</th>' +
      '<th class="text-right">Sharpe</th><th class="text-right">Win Rate</th>' +
      '<th class="text-right">Max DD</th><th class="text-right">Profit Factor</th>' +
      '<th class="text-right">Trades</th></tr></thead><tbody>';

    data.forEach((r, i) => {
      const rankCls = i === 0 ? 'rank-gold' : i === 1 ? 'rank-silver' : i === 2 ? 'rank-bronze' : 'rank-default';
      const retCls = cls(r.total_return_pct);
      const wrPct = r.win_rate || 0;
      const wrBarW = Math.min(100, wrPct);
      const sharpeCls = r.sharpe_ratio > 1 ? 'positive' : r.sharpe_ratio > 0 ? 'neutral' : 'negative';

      html += '<tr>' +
        '<td><div class="strat-rank ' + rankCls + '">' + (i+1) + '</div></td>' +
        '<td><strong>' + esc(r.strategy_name || 'Strategy ' + (i+1)) + '</strong>' +
          '<div style="font-size:.72rem;color:var(--text3);margin-top:2px">' + esc(r.signals || '') + '</div></td>' +
        '<td class="text-right mono ' + retCls + '">' + fmtPct(r.total_return_pct) + '</td>' +
        '<td class="text-right mono ' + sharpeCls + '">' + (r.sharpe_ratio||0).toFixed(2) + '</td>' +
        '<td class="text-right">' + wrPct.toFixed(1) + '%<div class="metric-bar"><div class="metric-bar-fill bar-green" style="width:' + wrBarW + '%"></div></div></td>' +
        '<td class="text-right mono negative">' + (r.max_drawdown_pct||0).toFixed(1) + '%</td>' +
        '<td class="text-right mono">' + (r.profit_factor||0).toFixed(2) + '</td>' +
        '<td class="text-right">' + (r.total_trades||0) + '</td></tr>';
    });
    html += '</tbody></table>';
    $('backtestResults').innerHTML = html;

    // Update leaderboard too
    updateLeaderboard(data);
  };

  function updateLeaderboard(data) {
    if (!data || !data.length) return;
    $('strat-count').textContent = data.length + ' strategies';
    // Sort by sharpe
    const sorted = [...data].sort((a,b) => (b.sharpe_ratio||0) - (a.sharpe_ratio||0));
    let html = '<table><thead><tr><th>#</th><th>Strategy</th><th class="text-right">Return</th>' +
      '<th class="text-right">Sharpe</th><th class="text-right">Win Rate</th>' +
      '<th class="text-right">PF</th></tr></thead><tbody>';
    sorted.slice(0,50).forEach((r,i) => {
      const rankCls = i === 0 ? 'rank-gold' : i === 1 ? 'rank-silver' : i === 2 ? 'rank-bronze' : 'rank-default';
      html += '<tr><td><div class="strat-rank ' + rankCls + '">' + (i+1) + '</div></td>' +
        '<td><strong>' + esc(r.strategy_name || '--') + '</strong></td>' +
        '<td class="text-right mono ' + cls(r.total_return_pct) + '">' + fmtPct(r.total_return_pct) + '</td>' +
        '<td class="text-right mono">' + (r.sharpe_ratio||0).toFixed(2) + '</td>' +
        '<td class="text-right">' + (r.win_rate||0).toFixed(1) + '%</td>' +
        '<td class="text-right mono">' + (r.profit_factor||0).toFixed(2) + '</td></tr>';
    });
    html += '</tbody></table>';
    $('leaderboardTable').innerHTML = html;
  }

  // ── Live Trading Page ──────────────
  async function updateLive() {
    const stats = await fetchJSON('/stats');
    if (!stats) return;
    $('lv-pnl').textContent = (stats.total_pnl >= 0 ? '+' : '-') + '$' + fmt(Math.abs(stats.total_pnl||0));
    $('lv-pnl').className = 'card-value ' + cls(stats.total_pnl);
    $('lv-trades').textContent = stats.total_trades || 0;
    $('lv-rejected').textContent = stats.rejected || 0;

    const status = await fetchJSON('/status');
    if (status) {
      $('lv-status').textContent = status.running ? 'RUNNING' : 'STOPPED';
      $('lv-status').className = 'card-value ' + (status.running ? 'positive' : 'negative');
      $('liveDot').style.background = status.running ? 'var(--green)' : 'var(--red)';
    }

    // Update log feed
    const logs = await fetchJSON('/logs/recent');
    if (logs && logs.lines) {
      const container = $('logLines');
      let html = '';
      for (const line of logs.lines.slice(-40)) {
        let c = 'color:var(--text3)';
        const l = line.toLowerCase();
        if (l.includes('error') || l.includes('❌')) c = 'color:var(--red)';
        else if (l.includes('✅') || l.includes('approved') || l.includes('profit')) c = 'color:var(--green)';
        else if (l.includes('entry') || l.includes('🔥')) c = 'color:var(--cyan)';
        else if (l.includes('rejected') || l.includes('🚫')) c = 'color:var(--amber)';
        html += '<div style="' + c + ';white-space:pre-wrap;word-break:break-all">' + esc(line) + '</div>';
      }
      container.innerHTML = html;
      container.scrollTop = container.scrollHeight;
    }
  }

  // ── Live Controls ──────────────────
  window.startScalper = async () => { await fetch('/scalper/start', {method:'POST'}); };
  window.stopScalper = async () => { await fetch('/scalper/stop', {method:'POST'}); };
  window.closeAll = async () => {
    if (!confirm('Close ALL positions?')) return;
    await fetch('/close-all', {method:'POST'});
  };

  // ── P&L Canvas ─────────────────────
  async function drawPnl() {
    const trades = await fetchJSON('/trades/closed');
    const canvas = $('pnlCanvas');
    if (!canvas || !trades) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr; canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    ctx.clearRect(0, 0, W, H);

    if (!trades.length) {
      ctx.fillStyle = '#555568'; ctx.font = '13px -apple-system,sans-serif';
      ctx.textAlign = 'center'; ctx.fillText('No closed trades yet', W/2, H/2);
      return;
    }

    const rev = [...trades].reverse();
    const pts = [{x:0,y:0}];
    let cum = 0;
    rev.forEach((t,i) => { cum += t.pnl; pts.push({x:i+1, y:cum}); });

    const maxX = pts.length-1;
    const ys = pts.map(p=>p.y);
    let minY = Math.min(...ys,0), maxY = Math.max(...ys,0);
    const pad = Math.max(Math.abs(maxY-minY)*.15, 10);
    minY -= pad; maxY += pad;
    const pL=55,pR=15,pT=10,pB=25,pW=W-pL-pR,pH=H-pT-pB;
    const tX = i => pL + (maxX>0 ? i/maxX*pW : pW/2);
    const tY = v => pT + pH - ((v-minY)/(maxY-minY))*pH;

    // Zero line
    ctx.strokeStyle='#2a2a3a';ctx.lineWidth=1;ctx.setLineDash([4,4]);
    ctx.beginPath();ctx.moveTo(pL,tY(0));ctx.lineTo(W-pR,tY(0));ctx.stroke();ctx.setLineDash([]);

    // Area
    const last = pts[pts.length-1].y;
    const gc = last>=0?[0,230,118]:[255,82,82];
    const g = ctx.createLinearGradient(0,tY(maxY),0,tY(minY));
    g.addColorStop(0,'rgba('+gc+',0.2)');g.addColorStop(1,'rgba('+gc+',0.01)');
    ctx.fillStyle=g;ctx.beginPath();ctx.moveTo(tX(0),tY(0));
    pts.forEach(p=>ctx.lineTo(tX(p.x),tY(p.y)));ctx.lineTo(tX(maxX),tY(0));ctx.closePath();ctx.fill();

    // Line
    ctx.strokeStyle=last>=0?'#00e676':'#ff5252';ctx.lineWidth=2;ctx.lineJoin='round';
    ctx.beginPath();pts.forEach((p,i)=>{const px=tX(p.x),py=tY(p.y);i===0?ctx.moveTo(px,py):ctx.lineTo(px,py);});ctx.stroke();

    // Dots
    for(let i=1;i<pts.length;i++){
      ctx.fillStyle=rev[i-1].pnl>=0?'#00e676':'#ff5252';
      ctx.beginPath();ctx.arc(tX(pts[i].x),tY(pts[i].y),3,0,Math.PI*2);ctx.fill();
    }

    // Label
    ctx.fillStyle=last>=0?'#00e676':'#ff5252';ctx.font='bold 11px -apple-system,sans-serif';
    ctx.textAlign='left';ctx.fillText((last>=0?'+':'')+' $'+last.toFixed(2),tX(maxX)+6,tY(last)+4);
  }

  // ── Autopilot State ─────────────────
  async function updateAutopilot() {
    const s = await fetchJSON('/api/autopilot/state');
    if (!s) return;

    // Phase badge
    const phaseEl = $('ap-phase');
    phaseEl.textContent = s.phase || 'IDLE';
    phaseEl.className = 'badge ' + (s.phase === 'RESEARCHING' ? 'badge-green' : s.phase === 'SCANNING' ? 'badge-green' : '');

    // Meta
    const lastR = s.last_research ? new Date(s.last_research).toLocaleTimeString() : 'never';
    $('ap-meta').textContent = 'Last research: ' + lastR;

    // Counters
    $('ap-tested').textContent = s.strategies_tested || 0;
    $('ap-scanned').textContent = s.symbols_scanned || 0;
    $('ap-active').textContent = (s.top_strategies || []).length;

    // Top strategies table
    const strats = s.top_strategies || [];
    $('ap-strat-count').textContent = strats.length;
    if (strats.length > 0) {
      let html = '<table><thead><tr><th>#</th><th>Strategy</th><th>Symbol</th><th class="text-right">Return</th><th class="text-right">Sharpe</th><th class="text-right">Win Rate</th><th>Status</th></tr></thead><tbody>';
      strats.forEach((st, i) => {
        const rankCls = i === 0 ? 'rank-gold' : i === 1 ? 'rank-silver' : i === 2 ? 'rank-bronze' : 'rank-default';
        const retCls = cls(st.total_return_pct || st.return_pct || 0);
        html += '<tr>' +
          '<td><div class="strat-rank ' + rankCls + '">' + (i+1) + '</div></td>' +
          '<td><strong>' + esc(st.strategy_name || st.name || '--') + '</strong></td>' +
          '<td>' + esc(st.symbol || '--') + '</td>' +
          '<td class="text-right mono ' + retCls + '">' + fmtPct(st.total_return_pct || st.return_pct || 0) + '</td>' +
          '<td class="text-right mono">' + (st.sharpe_ratio || st.sharpe || 0).toFixed(2) + '</td>' +
          '<td class="text-right">' + (st.win_rate || 0).toFixed(1) + '%</td>' +
          '<td><span class="badge badge-green" style="font-size:.7rem">ACTIVE</span></td></tr>';
      });
      html += '</tbody></table>';
      $('apStrategiesTable').innerHTML = html;
    }

    // Activity log
    const logs = s.research_log || [];
    if (logs.length > 0) {
      let html = '';
      for (const entry of logs.slice(-30)) {
        let c = 'color:var(--text3)';
        const l = (typeof entry === 'string' ? entry : entry.msg || '').toLowerCase();
        if (l.includes('research') || l.includes('tested')) c = 'color:var(--purple)';
        else if (l.includes('signal') || l.includes('buy') || l.includes('entry')) c = 'color:var(--cyan)';
        else if (l.includes('exit') || l.includes('closed')) c = 'color:var(--green)';
        else if (l.includes('error') || l.includes('fail')) c = 'color:var(--red)';
        const text = typeof entry === 'string' ? entry : (entry.time ? entry.time + ' | ' : '') + (entry.msg || JSON.stringify(entry));
        html += '<div style="' + c + '">' + esc(text) + '</div>';
      }
      $('apLog').innerHTML = html;
      $('apLog').scrollTop = $('apLog').scrollHeight;
    }

    // Update stats if autopilot has them
    if (s.stats) {
      const st = s.stats;
      if (st.total_trades > 0) {
        $('ov-trades').textContent = st.total_trades;
        const pnl = st.total_pnl || 0;
        $('ov-pnl').textContent = (pnl >= 0 ? '+' : '-') + '$' + fmt(Math.abs(pnl));
        $('ov-pnl').className = 'card-value ' + cls(pnl);
        const wr = st.total_trades > 0 ? (st.wins / st.total_trades * 100) : 0;
        $('ov-winrate').textContent = wr.toFixed(1) + '%';
        $('ov-winrate').className = 'card-value ' + (wr >= 50 ? 'positive' : 'negative');
        $('ov-pnl-sub').textContent = 'W:' + st.wins + ' L:' + st.losses;
      }
    }
  }

  // ── Init & Poll ────────────────────
  initCharts();
  updateTicker();
  updateOverview();
  updateAutopilot();

  setInterval(async () => {
    await Promise.allSettled([updateOverview(), updateTicker(), updateAutopilot(), updateLive(), drawPnl()]);
  }, 3000);

  // Refresh candles every 5 min
  setInterval(() => {
    loadCandles('BTC/USD','btc');
    loadCandles('ETH/USD','eth');
  }, 300000);
})();
</script>
</body>
</html>"""
