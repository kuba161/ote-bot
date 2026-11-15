/* Backtest dashboard — reads results.json written by run_backtest.py */
const ET = 'America/New_York';
const fmtTs = ts => new Date(ts * 1000).toLocaleString('en-GB',
  {timeZone: ET, day: '2-digit', month: '2-digit', year: '2-digit',
   hour: '2-digit', minute: '2-digit'});
const fmtD = ts => new Date(ts * 1000).toLocaleDateString('en-GB', {timeZone: ET});
const usd = x => (x >= 0 ? '+' : '−') + '$' + Math.abs(x).toFixed(2);
const cls = x => x >= 0 ? 'pos' : 'neg';

Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#21262d';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

fetch('results.json').then(r => r.json()).then(render).catch(e => {
  document.getElementById('sub').textContent =
    'Cannot load results.json — run the backtest and serve the site/ folder over HTTP. (' + e + ')';
});

// forward test (validate_forward.py) — optional: without the file the section stays hidden
fetch('forward.json').then(r => r.ok ? r.json() : null).then(F => F && renderForward(F)).catch(() => {});

// verdicts and notes come from validate_forward.py in Polish (its tests pin the wording)
const EN = [['(niestabilne)', '(unstable)'], ['(orientacyjny)', '(indicative)'],
            ['miesiace dodatnie', 'positive months']];
const en = t => EN.reduce((acc, [pl, e]) => acc.split(pl).join(e), String(t));

function renderForward(F) {
  const pf = s => s.profit_factor ?? '∞';
  const d = F.variants[0], fp = d.fwd.provable, ip = d.is.provable;
  const vcls = v => v.startsWith('GO') ? 'pos' : 'neg';
  const row = (k, s) => `<tr><td>${k}</td><td>${s.trades}</td><td class="${cls(s.pnl_total)}">${usd(s.pnl_total)}</td>` +
    `<td>${pf(s)}</td><td>${s.winrate}%</td><td class="${cls(s.expectancy)}">${usd(s.expectancy)}</td>` +
    `<td>${s.avg_r.toFixed(2)}R</td><td>$${s.max_drawdown.toFixed(0)}</td></tr>`;
  const head = '<tr><th></th><th>tr</th><th>PnL</th><th>PF</th><th>WR</th><th>exp/tr</th><th>avg R</th><th>maxDD</th></tr>';
  const months = Object.entries(d.fwd_months).map(([m, v]) =>
    `<span>${m}: <b class="${cls(v.pnl)}">${usd(v.pnl)}</b> (${v.trades} tr)</span>`).join(' · ');
  const vars = F.variants.map(r => {
    const f = r.fwd, pos = Object.values(r.fwd_months).filter(v => v.pnl > 0).length;
    return `<tr><td>${r.name}${r.name === 'default' ? ' ◀' : ''}</td><td>${r.is.provable.trades}</td>` +
      `<td class="${cls(r.is.provable.pnl_total)}">${usd(r.is.provable.pnl_total)}</td>` +
      `<td>${f.provable.trades}</td><td class="${cls(f.deny.pnl_total)}">${usd(f.deny.pnl_total)}</td>` +
      `<td class="${cls(f.allow.pnl_total)}">${usd(f.allow.pnl_total)}</td><td>${pf(f.provable)}</td>` +
      `<td>${pos}/${Object.keys(r.fwd_months).length}</td><td class="${vcls(r.verdict)}">${en(r.verdict)}</td></tr>`;
  }).join('');
  document.getElementById('forward').innerHTML =
    `<div class="sub" style="margin-bottom:12px">Parameters frozen on 27 Jun 2026 using data up to ${fmtD(F.is_period[1])}. ` +
    `Forward = ${fmtD(F.fwd_period[0])} – ${fmtD(F.fwd_period[1])}, never seen while choosing them. ` +
    `Gap ${fmtD(F.is_period[1])} – ${fmtD(F.fwd_period[0])}: TradingView no longer serves those 15m bars. ` +
    `Verdict (default): <b class="${vcls(d.verdict)}">${en(d.verdict)}</b> — ${en(d.why)}.</div>` +
    `<table>${head}${row('IS (original sample)', ip)}${row('FORWARD provable', fp)}` +
    `${row('FORWARD deny', d.fwd.deny)}${row('FORWARD allow', d.fwd.allow)}</table>` +
    `<div class="note">Forward months: ${months}<br>` +
    `Expectancy forward / IS = <b>${F.expectancy_ratio}</b> · buy&amp;hold MNQ: IS ${F.buy_hold_pct.is}% / ` +
    `forward ${F.buy_hold_pct.fwd}%</div>` +
    `<h2 style="margin-top:20px">Pre-registered hypotheses (written down before this data; the default does NOT change)</h2>` +
    `<table><tr><th>variant</th><th>IS tr</th><th>IS PnL</th><th>FWD tr</th><th>FWD deny</th>` +
    `<th>FWD allow</th><th>PF</th><th>months+</th><th>verdict</th></tr>${vars}</table>`;
  document.getElementById('fwd-wrap').hidden = false;
}

function render(R) {
  const s = R.stats, days = Math.round((R.period.to - R.period.from) / 86400);
  const tfs = (R.config.BIAS_TFS || ['15m', '1h', '4h', '1d']).join('/');
  document.getElementById('title').textContent = `Fib OTE ${R.config.ENTRY_FIB} + bias ${tfs} — MNQ1! backtest`;
  document.title = `Backtest — Fib OTE ${R.config.ENTRY_FIB} + bias ${tfs} (MNQ1!)`;
  document.getElementById('sub').textContent =
    `Window: ${fmtD(R.period.from)} – ${fmtD(R.period.to)} (${days} days, ${R.period.bars_15m} 15m bars) · ` +
    `entry at ${R.config.ENTRY_FIB} of the 15m Fib leg · exits: ${R.config.EXIT_MODE} · ` +
    `bias aligned on ${tfs} (read at: ${R.config.BIAS_AT}) · risk-based sizing`;

  // cards
  const cards = [
    ['Trades', s.trades, ''],
    ['Winrate', s.winrate + '%', s.winrate >= 50 ? 'pos' : 'gold'],
    ['Total PnL', usd(s.pnl_total), cls(s.pnl_total)],
    ['Profit factor', s.profit_factor ?? '∞', (s.profit_factor ?? 9) >= 1.5 ? 'pos' : (s.profit_factor >= 1 ? 'gold' : 'neg')],
    ['Expectancy', usd(s.expectancy) + '/trade', cls(s.expectancy)],
    ['Average R', s.avg_r.toFixed(2) + 'R', cls(s.avg_r)],
    ['Max drawdown', '$' + s.max_drawdown.toFixed(2), 'neg'],
  ];
  document.getElementById('cards').innerHTML = cards.map(([k, v, c]) =>
    `<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');

  // intrabar bracket: deny <= truth <= allow; headline = provable
  const vd = R.variant_deny, va = R.variant_allow;
  if (va) {
    document.getElementById('sub').innerHTML +=
      `<br>Headline = <b>${R.config.ENTRY_BAR_TP}</b> mode (TP on the entry bar only when it is ` +
      `certain regardless of the intrabar path). Bracket: deny ` +
      (vd ? `<b class="${cls(vd.pnl_total)}">${usd(vd.pnl_total)}</b> (PF ${vd.profit_factor}) · ` : '') +
      `allow <b class="${cls(va.pnl_total)}">${usd(va.pnl_total)}</b> (PF ${va.profit_factor}, ` +
      `WR ${va.winrate}%) — the intrabar truth lies in between.`;
  }

  // funnel
  const f = R.funnel;
  document.getElementById('funnel').innerHTML =
    `<span>15m bars while flat: <b>${f.bars}</b></span><span class="arr">→</span>` +
    `<span>bias aligned: <b>${f.bias_aligned}</b></span><span class="arr">→</span>` +
    `<span>price touched ${R.config.ENTRY_FIB}: <b>${f.cross}</b></span><span class="arr">→</span>` +
    `<span>rejected: leg <b>${f.rej_min_leg || 0}</b> · gap guard <b>${f.rej_gap_guard || 0}</b> · ` +
    `risk cap <b>${f.rej_maxrisk || 0}</b> · filter <b>${f.rej_filter}</b></span><span class="arr">→</span>` +
    `<span>entries: <b>${f.entries}</b></span><span class="arr">+</span>` +
    `<span>shadow: <b>${f.shadow || 0}</b></span>`;

  // filter vs shadow (per signal)
  const sc = R.shadow_compare;
  if (sc) {
    const pfTxt = x => x.profit_factor === null ? '∞' : x.profit_factor;
    t_shadow.innerHTML =
      `<tr><th></th><th>with filter (real)</th><th>without filter (shadow)</th></tr>` +
      `<tr><td>signals</td><td>${sc.real.trades}</td><td>${sc.shadow.trades}</td></tr>` +
      `<tr><td>winrate</td><td>${sc.real.winrate}%</td><td>${sc.shadow.winrate}%</td></tr>` +
      `<tr><td>PnL per signal</td><td class="${cls(sc.real.pnl_total)}">${usd(sc.real.pnl_total)}</td>` +
      `<td class="${cls(sc.shadow.pnl_total)}">${usd(sc.shadow.pnl_total)}</td></tr>` +
      `<tr><td>profit factor</td><td>${pfTxt(sc.real)}</td><td>${pfTxt(sc.shadow)}</td></tr>` +
      `<tr><td>expectancy</td><td class="${cls(sc.real.expectancy)}">${usd(sc.real.expectancy)}</td>` +
      `<td class="${cls(sc.shadow.expectancy)}">${usd(sc.shadow.expectancy)}</td></tr>` +
      `<tr><td>avg R</td><td class="${cls(sc.real.avg_r)}">${sc.real.avg_r.toFixed(2)}R</td>` +
      `<td class="${cls(sc.shadow.avg_r)}">${sc.shadow.avg_r.toFixed(2)}R</td></tr>`;
  }

  // parameter sweep
  if (R.sweep) {
    document.getElementById('sweep_wrap').style.display = '';
    const pf = x => x.profit_factor === null ? '∞' : x.profit_factor.toFixed(2);
    const pnl = x => `<span class="${cls(x.pnl_total)}">${usd(x.pnl_total)}</span>`;
    t_sweep.innerHTML =
      `<tr><th>variant</th><th>overrides</th><th>trades</th><th>WR</th><th>PnL deny</th>` +
      `<th>PnL prov</th><th>PnL allow</th><th>PF d</th><th>PF p</th><th>PF a</th>` +
      `<th>maxDD p</th><th>months +/−</th></tr>` +
      R.sweep.rows.map(row => {
        const d = row.res.deny, p = row.res.provable, a = row.res.allow;
        const ov = Object.entries(row.overrides)
          .map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ');
        const pos = Object.values(row.by_month).filter(v => v > 0).length;
        const neg = Object.values(row.by_month).filter(v => v <= 0).length;
        return `<tr><td>${row.name}</td><td style="white-space:normal">${ov || '—'}</td>` +
               `<td>${p.trades}</td><td>${p.winrate}%</td>` +
               `<td>${pnl(d)}</td><td>${pnl(p)}</td><td>${pnl(a)}</td>` +
               `<td>${pf(d)}</td><td>${pf(p)}</td><td>${pf(a)}</td>` +
               `<td>$${p.max_drawdown.toFixed(0)}</td><td>${pos}/${neg}</td></tr>`;
      }).join('');
    document.getElementById('sweep_note').textContent = R.sweep.criterion;
  }

  // equity + drawdown
  const eq = R.equity, labels = eq.map(p => fmtTs(p.ts)), cum = eq.map(p => p.cum);
  let peak = 0; const dd = cum.map(c => { peak = Math.max(peak, c); return +(peak - c).toFixed(2); });
  mkLine('equity', labels, cum, '#3fb950');
  mkLine('dd', labels, dd.map(x => -x), '#f85149');

  // R histogram
  const rs = R.r_values, edges = [];
  for (let e = -1.5; e <= 3.01; e += 0.5) edges.push(+e.toFixed(1));
  const counts = new Array(edges.length - 1).fill(0);
  rs.forEach(r => {
    for (let i = 0; i < edges.length - 1; i++)
      if (r >= edges[i] && r < edges[i + 1]) { counts[i]++; return; }
    if (r >= edges[edges.length - 1]) counts[counts.length - 1]++;
    if (r < edges[0]) counts[0]++;
  });
  new Chart(rhist, {type: 'bar', data: {
    labels: counts.map((_, i) => `${edges[i]}…${edges[i + 1]}R`),
    datasets: [{data: counts, backgroundColor: counts.map((_, i) => edges[i] >= 0 ? '#3fb95080' : '#f8514980')}]},
    options: {plugins: {legend: {display: false}}, scales: {y: {ticks: {precision: 0}}}}});

  // monthly
  const months = Object.keys(R.by_month).sort();
  new Chart(monthly, {type: 'bar', data: {labels: months,
    datasets: [{data: months.map(m => R.by_month[m].pnl),
                backgroundColor: months.map(m => R.by_month[m].pnl >= 0 ? '#3fb95080' : '#f8514980')}]},
    options: {plugins: {legend: {display: false}}}});

  // breakdown tables
  const bd = (obj, name) => {
    const keys = Object.keys(obj).sort((a, b) => obj[b].pnl - obj[a].pnl);
    return `<tr><th>${name}</th><th>trades</th><th>winrate</th><th>PnL</th></tr>` +
      keys.map(k => { const d = obj[k];
        return `<tr><td>${k}</td><td>${d.trades}</td><td>${(100 * d.wins / d.trades).toFixed(0)}%</td>` +
               `<td class="${cls(d.pnl)}">${usd(d.pnl)}</td></tr>`; }).join('');
  };
  t_filter.innerHTML = bd(R.by_filter, 'filter');
  t_side.innerHTML = bd(R.by_side, 'side');
  t_kz.innerHTML = bd(R.by_killzone, 'killzone');

  // config
  const showCfg = ['ENTRY_FIB', 'BIAS_METHOD', 'BIAS_TFS', 'BIAS_AT', 'PIVOT_LEN', 'STRUCT_PIVOT_LEN',
                   'EXIT_MODE', 'TP_MIN_R', 'TP_MAX_R', 'SL_BUFFER_TICKS', 'SESSION_FILTER', 'TRADE_SESSIONS',
                   'SIZING_MODE', 'RISK_PER_TRADE_USD', 'MAX_CONTRACTS', 'MAX_RISK_USD',
                   'FVG_MIN_PT', 'KEY_OPEN_MAX_TICKS', 'ENTRY_BAR_TP', 'GAP_GUARD', 'BOTH_HIT_RULE',
                   'SLIPPAGE_TICKS_ENTRY', 'SLIPPAGE_TICKS_STOP', 'COMMISSION_RT', 'DATA_END'];
  t_cfg.innerHTML = '<tr><th>parameter</th><th>value</th></tr>' +
    showCfg.map(k => `<tr><td>${k}</td><td>${JSON.stringify(R.config[k])}</td></tr>`).join('');

  // trades (MAE/MFE in R of risk_pt; "TP after SL" = post_tp_bars: how many bars after the stop
  // price reached the original TP — 0b is a candidate for intrabar ambiguity)
  t_trades.innerHTML =
    `<tr><th>#</th><th>entry (ET)</th><th>side</th><th>filter</th><th>kz</th><th>entry</th>
     <th>SL</th><th>TP</th><th>exit (ET)</th><th>exit</th><th>result</th><th>R</th>
     <th>MAE</th><th>MFE</th><th>TP after SL</th><th>PnL</th></tr>` +
    R.trades.map((t, i) =>
      `<tr><td>${i + 1}</td><td>${fmtTs(t.entry_ts)}</td>` +
      `<td><span class="tag ${t.side}">${t.side}</span></td>` +
      `<td><span class="tag f">${t.filter}</span></td><td>${t.kz}</td>` +
      `<td>${t.entry.toFixed(2)}</td><td>${t.sl.toFixed(2)}${t.be_moved ? '→BE' : ''}</td>` +
      `<td>${t.tp.toFixed(2)}</td>` +
      `<td>${fmtTs(t.exit_ts)}</td><td>${t.exit.toFixed(2)}</td>` +
      `<td class="${t.result === 'tp' ? 'pos' : 'neg'}">${t.result.toUpperCase()}</td>` +
      `<td class="${cls(t.r)}">${t.r.toFixed(2)}</td>` +
      `<td>${(t.mae_pt / t.risk_pt).toFixed(2)}R</td>` +
      `<td>${(t.mfe_pt / t.risk_pt).toFixed(2)}R</td>` +
      `<td>${t.result === 'sl' ? (t.post_tp_bars === null ? '—' : t.post_tp_bars + 'b') : ''}</td>` +
      `<td class="${cls(t.pnl)}">${usd(t.pnl)}</td></tr>`).join('');
}

function mkLine(id, labels, data, color) {
  new Chart(document.getElementById(id), {type: 'line',
    data: {labels, datasets: [{data, borderColor: color, backgroundColor: color + '22',
           fill: true, pointRadius: 2, tension: .25}]},
    options: {plugins: {legend: {display: false}},
              scales: {x: {ticks: {maxTicksLimit: 8}}}}});
}
