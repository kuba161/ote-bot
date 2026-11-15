#!/usr/bin/env node
// Eksport świec z wykresu TradingView do CSV (time,open,high,low,close,volume; ts w sekundach UTC).
//
//   node tvexport.mjs <SYMBOL> <outDir> [prefix] [res...]
//   node tvexport.mjs CME_MINI_DL:MNQ1! data/raw mnq 15 60 240 1D
//
// Jak to działa: przełącza wykres na symbol/interwał, w pętli przewija w tył przez
// timeScale().zoomToBarsRange z UJEMNYM indeksem (to wymusza doładowanie historii), aż liczba barów
// przestanie rosnąć, i czyta bary prosto z modelu serii. Plik zapisuje Node, nie przeglądarka
// (Blob download był potrzebny tylko dlatego, że CSP blokuje fetch na localhost).
// Na końcu przywraca symbol i interwał, które były na wykresie przed eksportem.
// TV oddaje ok. 3,3 mies. 15m, 1H od 05.2025, 4H od 2023, 1D od 2019 — więcej się nie da.
import CDP from 'chrome-remote-interface';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';

const [symbol, outDir, prefix = 'mnq', ...resArg] = process.argv.slice(2);
if (!symbol || !outDir) { console.error('usage: tvexport.mjs <SYMBOL> <outDir> [prefix] [res...]'); process.exit(1); }
const RES = resArg.length ? resArg : ['15', '60', '240', '1D'];
const NAME = { '15': '15m', '60': '1h', '240': '4h', '1D': '1d', 'D': '1d' };
const stamp = new Date().toISOString().slice(0, 10);

const targets = await (await fetch('http://localhost:9222/json/list')).json();
const t = targets.find(t => t.type === 'page' && t.url?.includes('tradingview.com/chart'));
if (!t) { console.error('No TradingView chart target'); process.exit(1); }
const c = await CDP({ host: 'localhost', port: 9222, target: t.id });
await c.Runtime.enable();
const ev = async (e) => {
  const r = await c.Runtime.evaluate({ expression: e, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result?.value;
};
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const CH = 'window.TradingViewApi._activeChartWidgetWV.value()';
const size = () => ev(`${CH}._chartWidget.model().mainSeries().bars().size()`);

// przełączenie z czekaniem na callback „dane gotowe"
const setSym = (s) => ev(`new Promise(r => { ${CH}.setSymbol(${JSON.stringify(s)}, () => r(true)); setTimeout(() => r(false), 15000); })`);
const setRes = (s) => ev(`new Promise(r => { ${CH}.setResolution(${JSON.stringify(s)}, () => r(true)); setTimeout(() => r(false), 15000); })`);

const prev = JSON.parse(await ev(`JSON.stringify({sym:${CH}.symbol(),res:${CH}.resolution()})`));
mkdirSync(outDir, { recursive: true });

try {
  await setSym(symbol);
  for (const res of RES) {
    await setRes(res);
    await sleep(1500);
    let n = await size(), stable = 0;
    while (stable < (+process.env.TV_STABLE || 4)) {
      await ev(`(function(){var ts=${CH}._chartWidget.model().timeScale();var f=ts.visibleBarsStrictRange();
                var a=f?f.firstBar():0; ts.zoomToBarsRange(a-2000, a+50); return true;})()`);
      await sleep(+process.env.TV_WAIT_MS || 1200);
      const m = await size();
      stable = m > n ? 0 : stable + 1;
      n = m;
    }
    const rows = JSON.parse(await ev(`(function(){var b=${CH}._chartWidget.model().mainSeries().bars();var out=[];
      b.each(function(i,v){ if(v&&v[1]!=null) out.push(v.slice(0,6)); return false; }); return JSON.stringify(out);})()`));
    const lines = ['time,open,high,low,close,volume', ...rows.map(r => r.map(x => x ?? 0).join(','))];
    const f = join(outDir, `${prefix}_${NAME[res] || res}_${stamp}.csv`);
    writeFileSync(f, lines.join('\n') + '\n');
    const d = (s) => new Date(s * 1000).toISOString().slice(0, 16);
    console.log(`${res.padEnd(4)} ${rows.length} barów  ${d(rows[0][0])} -> ${d(rows.at(-1)[0])} UTC  -> ${f}`);
  }
} finally {
  await setSym(prev.sym);
  await setRes(prev.res);
  console.log(`przywrócono wykres: ${prev.sym} ${prev.res}`);
  await c.close();
}
