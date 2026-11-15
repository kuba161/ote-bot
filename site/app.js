/* Dashboard backtestu — czyta results.json wygenerowany przez run_backtest.py */
const ET = 'America/New_York';
const fmtTs = ts => new Date(ts * 1000).toLocaleString('pl-PL',
  {timeZone: ET, day: '2-digit', month: '2-digit', year: '2-digit',
   hour: '2-digit', minute: '2-digit'});
const fmtD = ts => new Date(ts * 1000).toLocaleDateString('pl-PL', {timeZone: ET});
const usd = x => (x >= 0 ? '+' : '−') + '$' + Math.abs(x).toFixed(2);
const cls = x => x >= 0 ? 'pos' : 'neg';

Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#21262d';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

fetch('results.json').then(r => r.json()).then(render).catch(e => {
  document.getElementById('sub').textContent =
    'Nie mogę wczytać results.json — uruchom backtest i serwuj katalog site/ przez http.server. (' + e + ')';
});

// test forward (validate_forward.py) — opcjonalny: bez pliku sekcja zostaje ukryta
fetch('forward.json').then(r => r.ok ? r.json() : null).then(F => F && renderForward(F)).catch(() => {});

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
      `<td>${pos}/${Object.keys(r.fwd_months).length}</td><td class="${vcls(r.verdict)}">${r.verdict}</td></tr>`;
  }).join('');
  document.getElementById('forward').innerHTML =
    `<div class="sub" style="margin-bottom:12px">Parametry zamrożone 27.06 na danych do ${fmtD(F.is_period[1])}. ` +
    `Forward = ${fmtD(F.fwd_period[0])} – ${fmtD(F.fwd_period[1])}, nigdy nie widziany przy doborze. ` +
    `Dziura ${fmtD(F.is_period[1])} – ${fmtD(F.fwd_period[0])}: TV nie oddaje już tych świec 15m. ` +
    `Werdykt (default): <b class="${vcls(d.verdict)}">${d.verdict}</b> — ${d.why}.</div>` +
    `<table>${head}${row('IS (stara próba)', ip)}${row('FORWARD provable', fp)}` +
    `${row('FORWARD deny', d.fwd.deny)}${row('FORWARD allow', d.fwd.allow)}</table>` +
    `<div class="note">Miesiące forward: ${months}<br>` +
    `Expectancy forward / IS = <b>${F.expectancy_ratio}</b> · buy&amp;hold MNQ: IS ${F.buy_hold_pct.is}% / ` +
    `forward ${F.buy_hold_pct.fwd}%</div>` +
    `<h2 style="margin-top:20px">Hipotezy z R5 (zapisane przed tymi danymi, default się NIE zmienia)</h2>` +
    `<table><tr><th>wariant</th><th>IS tr</th><th>IS PnL</th><th>FWD tr</th><th>FWD deny</th>` +
    `<th>FWD allow</th><th>PF</th><th>mies+</th><th>werdykt</th></tr>${vars}</table>`;
  document.getElementById('fwd-wrap').hidden = false;
}

function render(R) {
  const s = R.stats, days = Math.round((R.period.to - R.period.from) / 86400);
  const tfs = (R.config.BIAS_TFS || ['15m', '1h', '4h', '1d']).join('/');
  // tytul z BIAS_TFS, zeby nie rozjechal sie z konfiguracja (dawniej na sztywno "4×TF")
  document.getElementById('title').textContent = `Fib OTE ${R.config.ENTRY_FIB} + bias ${tfs} — backtest MNQ1!`;
  document.title = `Backtest — Fib OTE ${R.config.ENTRY_FIB} + bias ${tfs} (MNQ1!)`;
  document.getElementById('sub').textContent =
    `Okno: ${fmtD(R.period.from)} – ${fmtD(R.period.to)} (${days} dni, ${R.period.bars_15m} barów 15m) · ` +
    `entry ${R.config.ENTRY_FIB} / TP ${R.config.TP_FIB} / SL ${R.config.SL_FIB} nogi Fib 15m · ` +
    `bias ${tfs} zgodny (ocena: ${R.config.BIAS_AT}) · 1× MNQ`;

  // karty
  const cards = [
    ['Trades', s.trades, ''],
    ['Winrate', s.winrate + '%', s.winrate >= 50 ? 'pos' : 'gold'],
    ['PnL łącznie', usd(s.pnl_total), cls(s.pnl_total)],
    ['Profit factor', s.profit_factor ?? '∞', (s.profit_factor ?? 9) >= 1.5 ? 'pos' : (s.profit_factor >= 1 ? 'gold' : 'neg')],
    ['Expectancy', usd(s.expectancy) + '/trade', cls(s.expectancy)],
    ['Średnie R', s.avg_r.toFixed(2) + 'R', cls(s.avg_r)],
    ['Max drawdown', '$' + s.max_drawdown.toFixed(2), 'neg'],
  ];
  document.getElementById('cards').innerHTML = cards.map(([k, v, c]) =>
    `<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');

  // widelki rozstrzygniecia intrabar: deny <= prawda <= allow; headline = provable
  const vd = R.variant_deny, va = R.variant_allow;
  if (va) {
    document.getElementById('sub').innerHTML +=
      `<br>Wynik główny = tryb <b>${R.config.ENTRY_BAR_TP}</b> (TP na barze wejścia tylko, gdy ` +
      `pewny niezależnie od ścieżki intrabar). Widełki: deny ` +
      (vd ? `<b class="${cls(vd.pnl_total)}">${usd(vd.pnl_total)}</b> (PF ${vd.profit_factor}) · ` : '') +
      `allow <b class="${cls(va.pnl_total)}">${usd(va.pnl_total)}</b> (PF ${va.profit_factor}, ` +
      `WR ${va.winrate}%) — prawda intrabar leży pomiędzy.`;
  }

  // lejek
  const f = R.funnel;
  document.getElementById('funnel').innerHTML =
    `<span>bary 15m bez pozycji: <b>${f.bars}</b></span><span class="arr">→</span>` +
    `<span>bias zgodny: <b>${f.bias_aligned}</b></span><span class="arr">→</span>` +
    `<span>cena dotknęła 0.79: <b>${f.cross}</b></span><span class="arr">→</span>` +
    `<span>odrzucone: noga <b>${f.rej_min_leg || 0}</b> · gap-guard <b>${f.rej_gap_guard || 0}</b> · ` +
    `filtr <b>${f.rej_filter}</b></span><span class="arr">→</span>` +
    `<span>wejścia: <b>${f.entries}</b></span><span class="arr">+</span>` +
    `<span>shadow: <b>${f.shadow || 0}</b></span>`;

  // filtr vs shadow (per-sygnal)
  const sc = R.shadow_compare;
  if (sc) {
    const pfTxt = x => x.profit_factor === null ? '∞' : x.profit_factor;
    t_shadow.innerHTML =
      `<tr><th></th><th>z filtrem (real)</th><th>bez filtra (shadow)</th></tr>` +
      `<tr><td>sygnały</td><td>${sc.real.trades}</td><td>${sc.shadow.trades}</td></tr>` +
      `<tr><td>winrate</td><td>${sc.real.winrate}%</td><td>${sc.shadow.winrate}%</td></tr>` +
      `<tr><td>PnL per-sygnał</td><td class="${cls(sc.real.pnl_total)}">${usd(sc.real.pnl_total)}</td>` +
      `<td class="${cls(sc.shadow.pnl_total)}">${usd(sc.shadow.pnl_total)}</td></tr>` +
      `<tr><td>profit factor</td><td>${pfTxt(sc.real)}</td><td>${pfTxt(sc.shadow)}</td></tr>` +
      `<tr><td>expectancy</td><td class="${cls(sc.real.expectancy)}">${usd(sc.real.expectancy)}</td>` +
      `<td class="${cls(sc.shadow.expectancy)}">${usd(sc.shadow.expectancy)}</td></tr>` +
      `<tr><td>śr. R</td><td class="${cls(sc.real.avg_r)}">${sc.real.avg_r.toFixed(2)}R</td>` +
      `<td class="${cls(sc.shadow.avg_r)}">${sc.shadow.avg_r.toFixed(2)}R</td></tr>`;
  }

  // sweep parametrow
  if (R.sweep) {
    document.getElementById('sweep_wrap').style.display = '';
    const pf = x => x.profit_factor === null ? '∞' : x.profit_factor.toFixed(2);
    const pnl = x => `<span class="${cls(x.pnl_total)}">${usd(x.pnl_total)}</span>`;
    t_sweep.innerHTML =
      `<tr><th>wariant</th><th>zmiany</th><th>trades</th><th>WR</th><th>PnL deny</th>` +
      `<th>PnL prov</th><th>PnL allow</th><th>PF d</th><th>PF p</th><th>PF a</th>` +
      `<th>maxDD p</th><th>mies +/−</th></tr>` +
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

  // histogram R
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

  // tabele breakdown
  const bd = (obj, name) => {
    const keys = Object.keys(obj).sort((a, b) => obj[b].pnl - obj[a].pnl);
    return `<tr><th>${name}</th><th>trades</th><th>winrate</th><th>PnL</th></tr>` +
      keys.map(k => { const d = obj[k];
        return `<tr><td>${k}</td><td>${d.trades}</td><td>${(100 * d.wins / d.trades).toFixed(0)}%</td>` +
               `<td class="${cls(d.pnl)}">${usd(d.pnl)}</td></tr>`; }).join('');
  };
  t_filter.innerHTML = bd(R.by_filter, 'filtr');
  t_side.innerHTML = bd(R.by_side, 'kierunek');
  t_kz.innerHTML = bd(R.by_killzone, 'killzone');

  // config
  const showCfg = ['ENTRY_FIB', 'TP_FIB', 'SL_FIB', 'MIN_LEG_PT', 'PIVOT_LEN', 'EMA_LEN',
                   'BIAS_AT', 'BIAS_TFS', 'FVG_MIN_PT', 'KEY_OPEN_MAX_TICKS', 'KEY_OPEN_WINDOW_MIN',
                   'NWOG_KEEP', 'ENTRY_BAR_TP', 'GAP_GUARD', 'SKIP_FIRST_BAR_AFTER_WEEKEND',
                   'BE_AT_FIB', 'POST_EXIT_BARS', 'SLIPPAGE_TICKS_ENTRY', 'SLIPPAGE_TICKS_STOP',
                   'COMMISSION_RT', 'BOTH_HIT_RULE'];
  t_cfg.innerHTML = '<tr><th>parametr</th><th>wartość</th></tr>' +
    showCfg.map(k => `<tr><td>${k}</td><td>${JSON.stringify(R.config[k])}</td></tr>`).join('');

  // trade'y (MAE/MFE w R od risk_pt; "TP po SL" = post_tp_bars: po ilu barach od SL
  // cena dotknela oryginalnego TP — 0b to kandydat na niejednoznacznosc intrabar)
  t_trades.innerHTML =
    `<tr><th>#</th><th>wejście (ET)</th><th>strona</th><th>filtr</th><th>kz</th><th>entry</th>
     <th>SL</th><th>TP</th><th>wyjście (ET)</th><th>exit</th><th>wynik</th><th>R</th>
     <th>MAE</th><th>MFE</th><th>TP po SL</th><th>PnL</th></tr>` +
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
