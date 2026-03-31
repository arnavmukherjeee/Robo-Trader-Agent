"""Single-file HTML dashboard for the Robo-Trader crypto scalping bot."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Robo-Trader Dashboard</title>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#0a0a0f;--surface:#12121a;--surface2:#1a1a26;--border:#2a2a3a;
    --text:#e0e0e8;--text2:#8888a0;--green:#00e676;--red:#ff5252;
    --blue:#448aff;--amber:#ffd740;--cyan:#18ffff;
    --radius:10px;--shadow:0 2px 12px rgba(0,0,0,.4);
  }
  html{font-size:14px}
  body{
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    background:var(--bg);color:var(--text);min-height:100vh;
    padding:0;overflow-x:hidden;
  }
  a{color:var(--blue);text-decoration:none}

  /* ── Header ──────────────────────── */
  .header{
    display:flex;align-items:center;justify-content:space-between;
    padding:16px 28px;background:var(--surface);
    border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100;
  }
  .header-left{display:flex;align-items:center;gap:14px}
  .logo{font-size:1.5rem;font-weight:700;letter-spacing:-.5px;color:#fff}
  .logo span{color:var(--green)}
  .pulse-dot{
    width:10px;height:10px;border-radius:50%;background:var(--green);
    display:inline-block;position:relative;
  }
  .pulse-dot.off{background:var(--red)}
  .pulse-dot::after{
    content:'';position:absolute;inset:-4px;border-radius:50%;
    background:var(--green);opacity:.4;animation:pulse 1.5s ease-out infinite;
  }
  .pulse-dot.off::after{background:var(--red)}
  @keyframes pulse{0%{transform:scale(1);opacity:.4}100%{transform:scale(2.2);opacity:0}}
  .status-label{font-size:.85rem;color:var(--text2)}

  .header-actions{display:flex;gap:10px}
  .btn{
    padding:8px 18px;border:none;border-radius:6px;font-size:.85rem;
    font-weight:600;cursor:pointer;transition:all .15s;letter-spacing:.3px;
  }
  .btn:active{transform:scale(.96)}
  .btn-start{background:var(--green);color:#000}
  .btn-start:hover{background:#00c864}
  .btn-stop{background:var(--red);color:#fff}
  .btn-stop:hover{background:#e04545}
  .btn-danger{background:transparent;border:1px solid var(--red);color:var(--red)}
  .btn-danger:hover{background:var(--red);color:#fff}
  .btn:disabled{opacity:.4;cursor:not-allowed;transform:none}

  /* ── Layout ──────────────────────── */
  .container{padding:20px 28px;max-width:1600px;margin:0 auto}

  /* ── Metric Cards ───────────────── */
  .cards{
    display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
    gap:14px;margin-bottom:20px;
  }
  .card{
    background:var(--surface);border:1px solid var(--border);
    border-radius:var(--radius);padding:18px 20px;
    transition:border-color .2s;
  }
  .card:hover{border-color:#3a3a50}
  .card-label{font-size:.75rem;text-transform:uppercase;letter-spacing:1px;color:var(--text2);margin-bottom:6px}
  .card-value{font-size:1.7rem;font-weight:700;transition:color .3s}
  .card-sub{font-size:.78rem;color:var(--text2);margin-top:4px}
  .positive{color:var(--green)}
  .negative{color:var(--red)}

  /* ── Tables ─────────────────────── */
  .panel{
    background:var(--surface);border:1px solid var(--border);
    border-radius:var(--radius);margin-bottom:20px;overflow:hidden;
  }
  .panel-header{
    display:flex;align-items:center;justify-content:space-between;
    padding:14px 20px;border-bottom:1px solid var(--border);
  }
  .panel-title{font-size:1rem;font-weight:600;display:flex;align-items:center;gap:8px}
  .badge{
    background:var(--surface2);border:1px solid var(--border);
    border-radius:12px;padding:1px 10px;font-size:.75rem;color:var(--text2);
  }
  table{width:100%;border-collapse:collapse}
  th{
    text-align:left;padding:10px 16px;font-size:.72rem;text-transform:uppercase;
    letter-spacing:.8px;color:var(--text2);background:var(--surface2);
    border-bottom:1px solid var(--border);
  }
  td{
    padding:10px 16px;font-size:.88rem;border-bottom:1px solid var(--border);
    transition:background .15s;
  }
  tr:last-child td{border-bottom:none}
  tr:hover td{background:rgba(255,255,255,.02)}
  .mono{font-family:'SF Mono',Consolas,'Courier New',monospace}
  .text-right{text-align:right}
  .empty-state{padding:40px;text-align:center;color:var(--text2);font-size:.9rem}

  /* ── Grid layout for tables ─────── */
  .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
  @media(max-width:900px){.grid-2{grid-template-columns:1fr}}

  /* ── Log Feed ───────────────────── */
  .log-feed{
    background:#08080e;border:1px solid var(--border);border-radius:var(--radius);
    padding:0;overflow:hidden;margin-bottom:20px;
  }
  .log-feed .panel-header{background:var(--surface)}
  .log-lines{
    padding:12px 16px;height:280px;overflow-y:auto;
    font-family:'SF Mono',Consolas,'Courier New',monospace;
    font-size:.78rem;line-height:1.7;color:var(--text2);
    scroll-behavior:smooth;
  }
  .log-lines::-webkit-scrollbar{width:6px}
  .log-lines::-webkit-scrollbar-track{background:transparent}
  .log-lines::-webkit-scrollbar-thumb{background:#333;border-radius:3px}
  .log-line{white-space:pre-wrap;word-break:break-all}
  .log-line.error{color:var(--red)}
  .log-line.warning{color:var(--amber)}
  .log-line.success{color:var(--green)}
  .log-line.info{color:var(--cyan)}

  /* ── P&L Chart ──────────────────── */
  .pnl-chart{
    position:relative;height:200px;padding:10px 16px;
    background:linear-gradient(180deg, rgba(0,230,118,.03) 0%, rgba(255,82,82,.03) 100%);
  }
  .pnl-chart canvas{width:100%!important;height:100%!important}
  .chart-zero-line{
    position:absolute;left:16px;right:16px;
    border-top:1px dashed var(--border);pointer-events:none;
  }

  /* ── Trade History Table ────────── */
  .trade-row-win{background:rgba(0,230,118,.04)}
  .trade-row-loss{background:rgba(255,82,82,.04)}
  .trades-scroll{max-height:350px;overflow-y:auto}
  .trades-scroll::-webkit-scrollbar{width:6px}
  .trades-scroll::-webkit-scrollbar-track{background:transparent}
  .trades-scroll::-webkit-scrollbar-thumb{background:#333;border-radius:3px}
  .pnl-bar{
    display:inline-block;height:14px;min-width:2px;border-radius:2px;
    vertical-align:middle;margin-right:6px;
  }
  .pnl-bar.win{background:var(--green)}
  .pnl-bar.loss{background:var(--red)}

  /* ── Footer ─────────────────────── */
  .footer{
    text-align:center;padding:20px;color:var(--text2);font-size:.75rem;
    border-top:1px solid var(--border);margin-top:10px;
  }

  /* ── Animations ─────────────────── */
  @keyframes fadeNum{0%{opacity:.5;transform:translateY(-2px)}100%{opacity:1;transform:translateY(0)}}
  .num-change{animation:fadeNum .3s ease}

  /* ── Responsive ─────────────────── */
  @media(max-width:600px){
    .header{padding:12px 16px;flex-direction:column;gap:12px}
    .container{padding:14px 12px}
    .cards{grid-template-columns:repeat(2,1fr);gap:10px}
    .card-value{font-size:1.3rem}
  }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="logo">Robo<span>-Trader</span></div>
    <div class="pulse-dot off" id="statusDot"></div>
    <span class="status-label" id="statusLabel">Offline</span>
  </div>
  <div class="header-actions">
    <button class="btn btn-start" id="btnStart" onclick="startScalper()">Start Scalper</button>
    <button class="btn btn-stop" id="btnStop" onclick="stopScalper()" disabled>Stop Scalper</button>
    <button class="btn btn-danger" id="btnCloseAll" onclick="closeAll()">Close All</button>
  </div>
</div>

<div class="container">
  <!-- Metric Cards -->
  <div class="cards">
    <div class="card">
      <div class="card-label">Equity</div>
      <div class="card-value" id="equity">--</div>
      <div class="card-sub" id="equitySub">Portfolio value</div>
    </div>
    <div class="card">
      <div class="card-label">Cash</div>
      <div class="card-value" id="cash">--</div>
      <div class="card-sub" id="buyingPower">Buying power: --</div>
    </div>
    <div class="card">
      <div class="card-label">Total P&amp;L</div>
      <div class="card-value" id="pnl">--</div>
      <div class="card-sub" id="pnlDetail">W: -- / L: --</div>
    </div>
    <div class="card">
      <div class="card-label">Win Rate</div>
      <div class="card-value" id="winRate">--</div>
      <div class="card-sub" id="winRateDetail">Best: -- / Worst: --</div>
    </div>
    <div class="card">
      <div class="card-label">Total Trades</div>
      <div class="card-value" id="totalTrades">--</div>
      <div class="card-sub" id="avgHold">Avg hold: --</div>
    </div>
  </div>

  <!-- Positions & Orders -->
  <div class="grid-2">
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Open Positions <span class="badge" id="posCount">0</span></div>
      </div>
      <div id="positionsTable">
        <div class="empty-state">No open positions</div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Recent Orders <span class="badge" id="orderCount">0</span></div>
      </div>
      <div id="ordersTable">
        <div class="empty-state">No recent orders</div>
      </div>
    </div>
  </div>

  <!-- Running P&L Chart -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Cumulative P&amp;L <span class="badge" id="cumPnl">$0.00</span></div>
    </div>
    <div class="pnl-chart">
      <canvas id="pnlCanvas"></canvas>
    </div>
  </div>

  <!-- Closed Trade History -->
  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Closed Trades <span class="badge" id="tradeCount">0</span></div>
    </div>
    <div class="trades-scroll" id="tradesTable">
      <div class="empty-state">No closed trades yet</div>
    </div>
  </div>

  <!-- Log Feed -->
  <div class="log-feed">
    <div class="panel-header">
      <div class="panel-title">Live Log Feed</div>
      <span class="badge" id="logStatus">Streaming</span>
    </div>
    <div class="log-lines" id="logLines">
      <div class="log-line info">Waiting for log data...</div>
    </div>
  </div>
</div>

<div class="footer">Robo-Trader Agent &mdash; Crypto Scalper Dashboard</div>

<script>
(function(){
  const $ = id => document.getElementById(id);
  let isRunning = false;
  let prevValues = {};

  function fmt(n, decimals=2) {
    if (n == null || isNaN(n)) return '--';
    return Number(n).toLocaleString('en-US', {minimumFractionDigits: decimals, maximumFractionDigits: decimals});
  }

  function fmtUsd(n) {
    if (n == null || isNaN(n)) return '--';
    const sign = n >= 0 ? '+' : '';
    return (n >= 0 ? '' : '') + '$' + fmt(Math.abs(n));
  }

  function animateValue(el, newText) {
    if (el.textContent !== newText) {
      el.textContent = newText;
      el.classList.remove('num-change');
      void el.offsetWidth;
      el.classList.add('num-change');
    }
  }

  function colorClass(val) {
    if (val > 0) return 'positive';
    if (val < 0) return 'negative';
    return '';
  }

  async function fetchJSON(url) {
    try {
      const r = await fetch(url);
      if (!r.ok) return null;
      return await r.json();
    } catch { return null; }
  }

  // ── Data fetchers ────────────────────

  async function updateAccount() {
    const d = await fetchJSON('/account');
    if (!d) return;
    animateValue($('equity'), '$' + fmt(d.equity));
    animateValue($('cash'), '$' + fmt(d.cash));
    $('buyingPower').textContent = 'Buying power: $' + fmt(d.buying_power);
    $('equitySub').textContent = 'Portfolio: $' + fmt(d.portfolio_value);
  }

  async function updateStats() {
    const d = await fetchJSON('/stats');
    if (!d) return;
    const pnlEl = $('pnl');
    const pnlVal = d.total_pnl || 0;
    animateValue(pnlEl, (pnlVal >= 0 ? '+' : '') + '$' + fmt(Math.abs(pnlVal)));
    pnlEl.className = 'card-value ' + colorClass(pnlVal);

    const wr = d.win_rate != null ? (d.win_rate * 100).toFixed(1) + '%' : '--';
    animateValue($('winRate'), wr);
    $('winRate').className = 'card-value ' + (d.win_rate >= 0.5 ? 'positive' : d.win_rate > 0 ? 'negative' : '');

    animateValue($('totalTrades'), String(d.total_trades || 0));
    $('pnlDetail').textContent = 'W: ' + (d.wins||0) + ' / L: ' + (d.losses||0);
    $('winRateDetail').textContent = 'Best: $' + fmt(d.biggest_win||0) + ' / Worst: -$' + fmt(Math.abs(d.biggest_loss||0));

    const hold = d.avg_hold_time_ms;
    if (hold != null && hold > 0) {
      let holdStr;
      if (hold < 1000) holdStr = hold.toFixed(0) + 'ms';
      else if (hold < 60000) holdStr = (hold/1000).toFixed(1) + 's';
      else holdStr = (hold/60000).toFixed(1) + 'm';
      $('avgHold').textContent = 'Avg hold: ' + holdStr;
    }
  }

  async function updateStatus() {
    const d = await fetchJSON('/status');
    if (!d) {
      setRunning(false);
      return;
    }
    setRunning(!!d.running);
  }

  function setRunning(running) {
    isRunning = running;
    const dot = $('statusDot');
    const label = $('statusLabel');
    if (running) {
      dot.className = 'pulse-dot';
      label.textContent = 'Running';
      $('btnStart').disabled = true;
      $('btnStop').disabled = false;
    } else {
      dot.className = 'pulse-dot off';
      label.textContent = 'Stopped';
      $('btnStart').disabled = false;
      $('btnStop').disabled = true;
    }
  }

  async function updatePositions() {
    const data = await fetchJSON('/positions');
    if (!data) return;
    $('posCount').textContent = data.length;
    if (data.length === 0) {
      $('positionsTable').innerHTML = '<div class="empty-state">No open positions</div>';
      return;
    }
    let html = '<table><thead><tr>';
    html += '<th>Symbol</th><th class="text-right">Qty</th><th class="text-right">Entry</th>';
    html += '<th class="text-right">Mkt Value</th><th class="text-right">Unrl P&L</th><th class="text-right">P&L %</th>';
    html += '</tr></thead><tbody>';
    for (const p of data) {
      const pnl = parseFloat(p.unrealized_pl || p.unrealized_pnl || 0);
      const pnlPct = parseFloat(p.unrealized_plpc || p.unrealized_pnl_pct || 0) * 100;
      const cls = colorClass(pnl);
      html += '<tr>';
      html += '<td><strong>' + (p.symbol||'--') + '</strong></td>';
      html += '<td class="text-right mono">' + (p.qty||p.quantity||'--') + '</td>';
      html += '<td class="text-right mono">$' + fmt(p.avg_entry_price||p.entry_price||0) + '</td>';
      html += '<td class="text-right mono">$' + fmt(p.market_value||0) + '</td>';
      html += '<td class="text-right mono ' + cls + '">' + (pnl>=0?'+':'') + '$' + fmt(Math.abs(pnl)) + '</td>';
      html += '<td class="text-right mono ' + cls + '">' + (pnlPct>=0?'+':'') + pnlPct.toFixed(2) + '%</td>';
      html += '</tr>';
    }
    html += '</tbody></table>';
    $('positionsTable').innerHTML = html;
  }

  async function updateOrders() {
    const data = await fetchJSON('/orders?status=closed');
    if (!data) return;
    const recent = data.slice(0, 10);
    $('orderCount').textContent = recent.length;
    if (recent.length === 0) {
      $('ordersTable').innerHTML = '<div class="empty-state">No recent orders</div>';
      return;
    }
    let html = '<table><thead><tr>';
    html += '<th>Symbol</th><th>Side</th><th class="text-right">Qty</th>';
    html += '<th class="text-right">Price</th><th>Status</th><th>Time</th>';
    html += '</tr></thead><tbody>';
    for (const o of recent) {
      const side = (o.side||'').toUpperCase();
      const sideClass = side === 'BUY' ? 'positive' : 'negative';
      const filled = o.filled_avg_price || o.average_price || o.limit_price || '--';
      const time = o.filled_at || o.submitted_at || o.created_at || '';
      let timeStr = '--';
      if (time) {
        try { timeStr = new Date(time).toLocaleTimeString(); } catch {}
      }
      html += '<tr>';
      html += '<td><strong>' + (o.symbol||'--') + '</strong></td>';
      html += '<td class="' + sideClass + '">' + side + '</td>';
      html += '<td class="text-right mono">' + (o.filled_qty||o.qty||'--') + '</td>';
      html += '<td class="text-right mono">$' + (filled !== '--' ? fmt(filled) : '--') + '</td>';
      html += '<td>' + (o.status||'--') + '</td>';
      html += '<td class="mono" style="color:var(--text2)">' + timeStr + '</td>';
      html += '</tr>';
    }
    html += '</tbody></table>';
    $('ordersTable').innerHTML = html;
  }

  async function updateLogs() {
    const d = await fetchJSON('/logs/recent');
    if (!d || !d.lines) return;
    const container = $('logLines');
    const lines = d.lines.slice(-30);
    let html = '';
    for (const line of lines) {
      let cls = 'log-line';
      const lower = line.toLowerCase();
      if (lower.includes('error') || lower.includes('exception') || lower.includes('traceback')) cls += ' error';
      else if (lower.includes('warning') || lower.includes('warn')) cls += ' warning';
      else if (lower.includes('success') || lower.includes('filled') || lower.includes('profit')) cls += ' success';
      else if (lower.includes('info') || lower.includes('start') || lower.includes('connect')) cls += ' info';
      html += '<div class="' + cls + '">' + escapeHtml(line) + '</div>';
    }
    container.innerHTML = html;
    container.scrollTop = container.scrollHeight;
  }

  function escapeHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Controls ─────────────────────────

  window.startScalper = async function() {
    $('btnStart').disabled = true;
    await fetch('/scalper/start', {method:'POST'});
    setTimeout(updateStatus, 500);
  };

  window.stopScalper = async function() {
    $('btnStop').disabled = true;
    await fetch('/scalper/stop', {method:'POST'});
    setTimeout(updateStatus, 500);
  };

  window.closeAll = async function() {
    if (!confirm('Close ALL open positions? This cannot be undone.')) return;
    $('btnCloseAll').disabled = true;
    await fetch('/close-all', {method:'POST'});
    $('btnCloseAll').disabled = false;
    setTimeout(updatePositions, 500);
  };

  // ── P&L Chart (pure canvas, no library) ───────

  function drawPnlChart(trades) {
    const canvas = $('pnlCanvas');
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    ctx.clearRect(0, 0, W, H);

    if (!trades || trades.length === 0) {
      ctx.fillStyle = '#8888a0';
      ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No closed trades yet', W/2, H/2);
      return;
    }

    // Build cumulative P&L data points (oldest → newest)
    const reversed = [...trades].reverse();
    const points = [{x:0, y:0}];
    let cum = 0;
    for (let i = 0; i < reversed.length; i++) {
      cum += reversed[i].pnl;
      points.push({x: i+1, y: cum});
    }

    const maxX = points.length - 1;
    const yVals = points.map(p => p.y);
    let minY = Math.min(...yVals, 0);
    let maxY = Math.max(...yVals, 0);
    const yPad = Math.max(Math.abs(maxY - minY) * 0.15, 10);
    minY -= yPad; maxY += yPad;

    const padL = 60, padR = 20, padT = 15, padB = 30;
    const plotW = W - padL - padR, plotH = H - padT - padB;

    function toX(i) { return padL + (maxX > 0 ? (i / maxX) * plotW : plotW/2); }
    function toY(v) { return padT + plotH - ((v - minY) / (maxY - minY)) * plotH; }

    // Zero line
    const zeroY = toY(0);
    ctx.strokeStyle = '#2a2a3a';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padL, zeroY);
    ctx.lineTo(W - padR, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Y-axis labels
    ctx.fillStyle = '#8888a0';
    ctx.font = '11px SF Mono, Consolas, monospace';
    ctx.textAlign = 'right';
    const ySteps = 5;
    for (let i = 0; i <= ySteps; i++) {
      const val = minY + (maxY - minY) * (i / ySteps);
      const y = toY(val);
      ctx.fillText('$' + val.toFixed(0), padL - 8, y + 4);
      ctx.strokeStyle = '#1a1a26';
      ctx.lineWidth = 0.5;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W-padR, y); ctx.stroke();
    }

    // X-axis labels
    ctx.textAlign = 'center';
    const xStep = Math.max(1, Math.floor(maxX / 8));
    for (let i = 0; i <= maxX; i += xStep) {
      ctx.fillText('#' + i, toX(i), H - 8);
    }

    // Area fill
    const lastY = points[points.length-1].y;
    const gradColor = lastY >= 0 ? [0,230,118] : [255,82,82];
    const grad = ctx.createLinearGradient(0, toY(maxY), 0, toY(minY));
    grad.addColorStop(0, 'rgba('+gradColor.join(',')+',0.25)');
    grad.addColorStop(1, 'rgba('+gradColor.join(',')+',0.01)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(toX(0), zeroY);
    for (const p of points) ctx.lineTo(toX(p.x), toY(p.y));
    ctx.lineTo(toX(maxX), zeroY);
    ctx.closePath();
    ctx.fill();

    // Line
    ctx.strokeStyle = lastY >= 0 ? '#00e676' : '#ff5252';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    for (let i = 0; i < points.length; i++) {
      const px = toX(points[i].x), py = toY(points[i].y);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.stroke();

    // Dots for each trade
    for (let i = 1; i < points.length; i++) {
      const px = toX(points[i].x), py = toY(points[i].y);
      const trPnl = reversed[i-1].pnl;
      ctx.fillStyle = trPnl >= 0 ? '#00e676' : '#ff5252';
      ctx.beginPath();
      ctx.arc(px, py, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Current P&L label
    const lastPx = toX(maxX), lastPy = toY(lastY);
    ctx.fillStyle = lastY >= 0 ? '#00e676' : '#ff5252';
    ctx.font = 'bold 12px -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText((lastY>=0?'+':'') + '$' + lastY.toFixed(2), lastPx + 8, lastPy + 4);
  }

  // ── Closed Trades Table ─────────────────

  async function updateClosedTrades() {
    const trades = await fetchJSON('/trades/closed');
    if (!trades) return;
    $('tradeCount').textContent = trades.length;

    // Update cumulative P&L badge
    const cumPnl = trades.length > 0 ? trades[0].cumulative_pnl : 0;
    const cumEl = $('cumPnl');
    cumEl.textContent = (cumPnl >= 0 ? '+' : '') + '$' + fmt(Math.abs(cumPnl));
    cumEl.style.color = cumPnl >= 0 ? 'var(--green)' : 'var(--red)';

    // Draw chart
    drawPnlChart(trades);

    if (trades.length === 0) {
      $('tradesTable').innerHTML = '<div class="empty-state">No closed trades yet</div>';
      return;
    }

    // Find max absolute PnL for bar scaling
    const maxAbsPnl = Math.max(...trades.map(t => Math.abs(t.pnl)), 1);

    let html = '<table><thead><tr>';
    html += '<th>Symbol</th><th>P&amp;L</th><th class="text-right">Entry</th>';
    html += '<th class="text-right">Exit</th><th class="text-right">Size</th>';
    html += '<th class="text-right">Cumul.</th><th>Time</th>';
    html += '</tr></thead><tbody>';
    for (const t of trades) {
      const isWin = t.pnl >= 0;
      const cls = isWin ? 'trade-row-win' : 'trade-row-loss';
      const pnlCls = isWin ? 'positive' : 'negative';
      const barW = Math.max(2, (Math.abs(t.pnl) / maxAbsPnl) * 60);
      const barCls = isWin ? 'win' : 'loss';
      let timeStr = '--';
      if (t.exit_time) {
        try { timeStr = new Date(t.exit_time).toLocaleTimeString(); } catch {}
      }
      const cumCls = t.cumulative_pnl >= 0 ? 'positive' : 'negative';
      html += '<tr class="' + cls + '">';
      html += '<td><strong>' + t.symbol + '</strong></td>';
      html += '<td class="' + pnlCls + '"><span class="pnl-bar ' + barCls + '" style="width:' + barW + 'px"></span>' + (isWin?'+':'') + '$' + fmt(Math.abs(t.pnl)) + ' <span style="opacity:.6">(' + (isWin?'+':'') + t.pnl_pct.toFixed(2) + '%)</span></td>';
      html += '<td class="text-right mono">$' + fmt(t.entry_price) + '</td>';
      html += '<td class="text-right mono">$' + fmt(t.exit_price) + '</td>';
      html += '<td class="text-right mono">$' + fmt(t.notional) + '</td>';
      html += '<td class="text-right mono ' + cumCls + '">' + (t.cumulative_pnl>=0?'+':'') + '$' + fmt(Math.abs(t.cumulative_pnl)) + '</td>';
      html += '<td class="mono" style="color:var(--text2)">' + timeStr + '</td>';
      html += '</tr>';
    }
    html += '</tbody></table>';
    $('tradesTable').innerHTML = html;
  }

  // ── Polling Loop ─────────────────────

  async function refreshAll() {
    await Promise.allSettled([
      updateAccount(),
      updateStats(),
      updateStatus(),
      updatePositions(),
      updateOrders(),
      updateClosedTrades(),
      updateLogs(),
    ]);
  }

  refreshAll();
  setInterval(refreshAll, 3000);
})();
</script>
</body>
</html>"""
