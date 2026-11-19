// JS motorunu Python modeliyle karsilastirir.
// NOT: tohumlu rastgelelik ureteci iki dilde farkli (Python Mersenne,
// JS mulberry32), bu yuzden jitter/kayip iceren kosularda kucuk sapma normaldir.
import { defaults, simulate } from './engine.js';

const cases = [
  ['nominal', p => p],
  ['gecikme 30 ms / tork rampasi', p => { p.linkDeck = { ...p.linkDeck, latency: 30e-3 }; return p; }],
  ['gecikme 30 ms / enkoder', p => { p.linkDeck = { ...p.linkDeck, latency: 30e-3 }; p.fallbackEstimator = true; return p; }],
  ['akim WCET 120us / queue', p => { p.taskInner = { ...p.taskInner, exec: 120e-6, jitter: 24e-6 }; p.overrunPolicy = 'queue'; return p; }],
  ['akim WCET 120us / skip', p => { p.taskInner = { ...p.taskInner, exec: 120e-6, jitter: 24e-6 }; return p; }],
  ['PCS kaybi t=1.2 s', p => { p.pcsLossTime = 1.2; return p; }],
  ['kopma 1000 ms / enkoder', p => { p.netOutageStart = 0.9; p.netOutageDur = 1.0; p.fallbackEstimator = true; return p; }],
  ['12 t @ 68 m/s', p => { p.mass = 12000; p.entrySpeed = 68; return p; }],
  ['akim cevrimi periyodu 1000us', p => { p.taskInner = { ...p.taskInner, period: 1000e-6 }; return p; }],
];

console.log('durum'.padStart(30), 'durdu'.padStart(7), 'runout'.padStart(8),
  'g'.padStart(6), 'hookkN'.padStart(8), 'RMS'.padStart(7), 'turb%'.padStart(7));
for (const [name, mut] of cases) {
  const p = mut(defaults());
  const r = simulate(p, 100);
  const m = r.metrics;
  console.log(name.padStart(30), String(m.stopped).padStart(7),
    m.runout.toFixed(1).padStart(8), m.peakG.toFixed(2).padStart(6),
    (m.peakHook / 1e3).toFixed(0).padStart(8), m.trackRms.toFixed(2).padStart(7),
    (100 * r.energy.twisterShare).toFixed(1).padStart(7));
}
