// AAG-Clone fizik + kontrol + gercek zamanli katman — Python modelinin JS portu.
// aag/plant.py, aag/control.py, aag/rt.py, aag/sim.py ile birebir ayni denklemler.
// Dogrulama: ui/verify.js nominal kosuyu Python ciktisi ile karsilastirir.

const NSTATE = 16;
const IX = 0, IV = 1, ISD = 2, IW = 3, IZ = 4, II = 5, IVB = 6,
      IEWT = 7, IEMOT = 8, IECH = 9, IERL = 10, IEDMP = 11,
      IETHR = 12, IEROLL = 13, ITH = 14, IEFR = 15;

const X_ENGAGE = 6.0, X_RAMP = 28.0, DSDX_FLOOR = 0.15, INTEG_CLAMP = 2.0;

// --- varsayilan parametreler (aag/params.py ile ayni; HEPSI VARSAYIM) -------
function defaults() {
  return {
    mass: 22000, entrySpeed: 65, thrust: 100e3, rollResist: 6e3,
    halfSpan: 15.0,
    kCable: 4.0e5, cCable: 1.0e4, kShock: 3.0e5, cShockRef: 6.0e4,
    wRef: 18000, shockExp: 1.0, shockKExp: 1.0, shockScheduling: true,
    drumRadius: 0.55, drumInertia: 300.0, drumFriction: 120.0,
    kWt: 5.90, kWtModelErr: 0.0,
    kt: 30.0, rPh: 0.004, lPh: 0.4e-3, iMax: 7500.0, tMax: 220e3,
    rippleAmp: 0.0, rippleOrder: 6.0,
    vNom: 6500, vMax: 7500, vChop: 7000, rChop: 0.05, cBank: 1.5,
    // gercek zamanli
    baseDt: 5.0e-5, innerBandwidth: 400.0,
    watchdogTimeout: 0.020, watchdogHold: 0.050,
    overrunPolicy: 'skip', fallbackEstimator: false,
    deckRate: 1000.0, seed: 20261118,
    taskSupervisor: { period: 1 / 100, exec: 120e-6, jitter: 20e-6, overrunProb: 0, overrunFactor: 3 },
    taskTrajectory: { period: 1 / 500, exec: 80e-6, jitter: 15e-6, overrunProb: 0, overrunFactor: 3 },
    taskOuter:      { period: 1 / 1000, exec: 150e-6, jitter: 30e-6, overrunProb: 0, overrunFactor: 3 },
    taskInner:      { period: 1 / 10000, exec: 25e-6, jitter: 5e-6, overrunProb: 0, overrunFactor: 3 },
    linkDeck: { latency: 1.0e-3, jitter: 0.2e-3, dropout: 0, burstProb: 0, burstExtra: 0 },
    linkTorque: { latency: 0, jitter: 0, dropout: 0, burstProb: 0, burstExtra: 0 },
    // arizalar
    pcsLossTime: -1, pcsCAfter: 0.02, pcsDisableMotor: true,
    netOutageStart: -1, netOutageDur: 0,
    weightEstError: 0,
    tMax_: 6.0,
    // limitler
    limPeakG: 4.5, limHook: 1.10e6, limRunout: 103.0, limRms: 3.0, limVbus: 7500,
  };
}

// --- kazanc bin'leri --------------------------------------------------------
const WEIGHT_EDGES = [14000, 18000, 22000];
const SPEED_EDGES = [56, 64, 72];
const RUNOUT_BY_SPEED = [66.0, 82.0, 97.0, 101.0];

function binOf(mass, speed) {
  let i = 0, j = 0;
  for (const e of WEIGHT_EDGES) if (mass > e) i++;
  for (const e of SPEED_EDGES) if (speed > e) j++;
  return [i, j];
}
function gainsOf(mass, speed) {
  const [i, j] = binOf(mass, speed);
  return { kp: 6.0e3 + 4.0e3 * i + 1.5e3 * j,
           ki: 9.0e3 + 6.0e3 * i + 2.0e3 * j,
           runout: RUNOUT_BY_SPEED[j], bin: [i, j] };
}

// --- tohumlu rastgelelik (surecler arasi tekrar uretilebilir) ---------------
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function strHash(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
const rngFor = (seed, name) => mulberry32(strHash(seed + ':' + name));

// --- geometri ---------------------------------------------------------------
const payout = (x, b) => 2.0 * (Math.sqrt(x * x + b * b) - b);
const dpayout = (x, b) => 2.0 * x / Math.sqrt(x * x + b * b);

// --- gecikmeli ag baglantisi -------------------------------------------------
class DelayLink {
  constructor(spec, rng) {
    this.spec = spec; this.rng = rng;
    this.q = []; this.last = null; this.maxStale = 0; this.drops = 0; this.sent = 0;
    this.dropTimes = [];
  }
  send(t, value, blocked) {
    const s = this.spec; this.sent++;
    if (blocked || (s.dropout > 0 && this.rng() < s.dropout)) {
      this.drops++; this.dropTimes.push(t); return;
    }
    let lat = s.latency;
    if (s.jitter > 0) lat += (this.rng() * 2 - 1) * s.jitter;
    if (s.burstProb > 0 && this.rng() < s.burstProb) lat += s.burstExtra;
    if (lat < 0) lat = 0;
    this.q.push([t + lat, t, value]);
  }
  recv(t) {
    if (this.q.length) {
      const keep = [];
      for (const it of this.q) {
        if (it[0] <= t + 1e-12) {
          if (this.last === null || it[1] >= this.last[0]) this.last = [it[1], it[2]];
        } else keep.push(it);
      }
      this.q = keep;
    }
    if (this.last === null) return [null, 0];
    const stale = t - this.last[0];
    if (stale > this.maxStale) this.maxStale = stale;
    return [this.last[1], stale];
  }
}

// --- referans profili --------------------------------------------------------
function refProfile(x, v0, xf) {
  const aNom = v0 * v0 / (2.0 * Math.max(1.0, xf - 0.5 * (X_ENGAGE + X_RAMP)));
  if (x < X_ENGAGE) return [v0, 0.0];
  if (x < X_RAMP) {
    const f = (x - X_ENGAGE) / (X_RAMP - X_ENGAGE);
    const v2 = v0 * v0 - aNom * Math.pow(x - X_ENGAGE, 2) / (X_RAMP - X_ENGAGE);
    return [Math.sqrt(Math.max(0, v2)), aNom * f];
  }
  const v2 = v0 * v0 - aNom * (X_RAMP - X_ENGAGE) - 2.0 * aNom * (x - X_RAMP);
  return [Math.sqrt(Math.max(0, v2)), aNom];
}

// --- ana kosu ----------------------------------------------------------------
export function simulate(p, traceEvery = 20) {
  const b = p.halfSpan;
  const mEst = p.mass + p.weightEstError;
  const cShock = p.shockScheduling
    ? p.cShockRef * Math.pow(mEst / p.wRef, p.shockExp) : p.cShockRef;
  const kShockEff = p.shockScheduling
    ? p.kShock * Math.pow(mEst / p.wRef, p.shockKExp) : p.kShock;

  const g = gainsOf(mEst, p.entrySpeed);
  const wc = 2 * Math.PI * p.innerBandwidth;
  const kpI = p.lPh * wc, kiI = p.rPh * wc;

  // durum
  const y = new Float64Array(NSTATE);
  y[IV] = p.entrySpeed; y[IVB] = p.vNom;
  let cEff = p.cBank;

  // kontrolcu "blackboard"
  const ctrl = {
    vRef: p.entrySpeed, tMotCmd: 0, iCmd: 0, uVolt: 0,
    motorEnabled: true, degraded: false, degradeT0: -1,
    integO: 0, integI: 0, lastGoodTCmd: 0, watchdogEvents: 0,
    kp: g.kp, ki: g.ki, runoutTarget: g.runout, bin: g.bin,
  };

  const deck = new DelayLink(p.linkDeck, rngFor(p.seed, 'link_deck'));
  const torque = new DelayLink(p.linkTorque, rngFor(p.seed, 'link_torque'));

  const meas = {
    deck: (t) => { const [v, s] = deck.recv(t); return v === null ? [[y[IX], y[IV]], 0] : [v, s]; },
    drumPayout: () => y[ISD],
    omega: () => y[IW],
    current: () => y[II],
    vbus: () => y[IVB],
    torqueCmd: (t) => { const [v, s] = torque.recv(t); return [v === null ? 0 : v, s]; },
  };

  function estimateFromEncoder(t) {
    const sd = meas.drumPayout(), w = meas.omega();
    const r = 0.5 * sd + b;
    const x = Math.sqrt(Math.max(0, r * r - b * b));
    const d = dpayout(x, b);
    return [x, d > 0.05 ? w * p.drumRadius / d : 0];
  }

  // --- gorevler
  function taskSupervisor(t) {
    const [, stale] = meas.deck(t);
    const out = {}, st = {};
    const bn = binOf(mEst, p.entrySpeed);
    const gg = gainsOf(mEst, p.entrySpeed);
    out.bin = bn; out.kp = gg.kp; out.ki = gg.ki; out.runoutTarget = gg.runout;
    if (stale > p.watchdogTimeout) {
      out.degraded = true;
      if (!ctrl.degraded && ctrl.degradeT0 < 0) {
        st.watchdogEvents = ctrl.watchdogEvents + 1; st.degradeT0 = t;
      }
    } else { out.degraded = false; st.degradeT0 = -1; }
    out.motorEnabled = !(p.pcsLossTime >= 0 && p.pcsLossTime <= t && p.pcsDisableMotor);
    return [st, out];
  }

  function taskTrajectory(t) {
    let x;
    if (ctrl.degraded && p.fallbackEstimator) x = estimateFromEncoder(t)[0];
    else x = meas.deck(t)[0][0];
    return [{}, { vRef: refProfile(x, p.entrySpeed, ctrl.runoutTarget)[0] }];
  }

  function taskOuter(t) {
    let x, v;
    const dt = p.taskOuter.period;
    if (ctrl.degraded && !p.fallbackEstimator) {
      const held = ctrl.degradeT0 >= 0 ? t - ctrl.degradeT0 : 0;
      const hold = p.watchdogHold;
      const tc = held <= hold ? ctrl.lastGoodTCmd
        : ctrl.lastGoodTCmd * Math.max(0, 1 - (held - hold) / hold);
      return [{}, { tMotCmd: tc, iCmd: tc / p.kt }];
    }
    if (ctrl.degraded) { [x, v] = estimateFromEncoder(t); }
    else { const d = meas.deck(t); x = d[0][0]; v = d[0][1]; }
    const w = meas.omega();
    if (x < X_ENGAGE) return [{ integO: 0, lastGoodTCmd: 0 }, { tMotCmd: 0, iCmd: 0 }];
    const aRef = refProfile(x, p.entrySpeed, ctrl.runoutTarget)[1];
    const fReq = mEst * aRef + p.thrust;
    const dsdx = Math.max(DSDX_FLOOR, dpayout(x, b));
    const tShaft = (fReq / dsdx) * p.drumRadius;
    const kEst = p.kWt * (1 + p.kWtModelErr);
    const tWtEst = kEst * w * Math.abs(w);
    const e = v - ctrl.vRef;
    const raw = tShaft - tWtEst + ctrl.kp * e + ctrl.ki * ctrl.integO;
    const cmd = Math.max(-p.tMax, Math.min(p.tMax, raw));
    let integ = ctrl.integO;
    if (x >= X_RAMP && (Math.abs(raw - cmd) < 1e-9 || (raw - cmd) * e < 0)) {
      integ = Math.max(-INTEG_CLAMP, Math.min(INTEG_CLAMP, ctrl.integO + e * dt));
    }
    return [{ integO: integ, lastGoodTCmd: cmd }, { tMotCmd: cmd, iCmd: cmd / p.kt }];
  }

  function taskInner(t) {
    const dt = p.taskInner.period;
    const i = meas.current(), w = meas.omega();
    const emf = p.kt * w;
    let icmd = meas.torqueCmd(t)[0];
    icmd = Math.max(-p.iMax, Math.min(p.iMax, icmd));
    const e = icmd - i;
    const raw = kpI * e + kiI * ctrl.integI;
    const vb = meas.vbus();
    const u = Math.max(emf - vb, Math.min(emf, raw));
    let integ = ctrl.integI;
    if (Math.abs(raw - u) < 1e-9 || (raw - u) * e < 0) integ = ctrl.integI + e * dt;
    return [{ integI: integ }, { uVolt: u }];
  }

  function applyOutput(out, t) {
    for (const k in out) {
      if (k === 'degradeT0') continue;
      ctrl[k] = out[k];
      if (k === 'iCmd') torque.send(t, out[k], false);
    }
  }
  function applyState(st) {
    for (const k in st) {
      if (k === 'degradeT0') {
        if (st[k] >= 0 && ctrl.degradeT0 < 0) ctrl.degradeT0 = st[k];
        else if (st[k] < 0) ctrl.degradeT0 = -1;
      } else ctrl[k] = st[k];
    }
  }

  const mkTask = (spec, fn, name) => ({
    spec, fn, rng: rngFor(p.seed, name), next: 0, pending: [], prevFinish: 0,
    misses: 0, releases: 0, maxLat: 0, sumLat: 0, skipped: 0, name,
  });
  const tasks = [
    mkTask(p.taskSupervisor, taskSupervisor, 'supervisor'),
    mkTask(p.taskTrajectory, taskTrajectory, 'trajectory'),
    mkTask(p.taskOuter, taskOuter, 'outer'),
    mkTask(p.taskInner, taskInner, 'inner'),
  ];
  const skipOverrun = p.overrunPolicy === 'skip';
  function execTime(tk) {
    let e = tk.spec.exec;
    if (tk.spec.jitter > 0) e += (tk.rng() * 2 - 1) * tk.spec.jitter;
    if (tk.spec.overrunProb > 0 && tk.rng() < tk.spec.overrunProb) e *= tk.spec.overrunFactor;
    return Math.max(0, e);
  }
  function schedStep(t) {
    for (const tk of tasks) {
      if (tk.pending.length) {
        const still = [];
        for (const it of tk.pending) {
          if (it[0] <= t + 1e-12) applyOutput(it[1], it[0]); else still.push(it);
        }
        tk.pending = still;
      }
    }
    for (const tk of tasks) {
      while (t + 1e-12 >= tk.next) {
        const rel = tk.next;
        if (skipOverrun && tk.prevFinish > rel + 1e-12) {
          tk.skipped++; tk.misses++; tk.next += tk.spec.period; continue;
        }
        const [st, out] = tk.fn(rel);
        applyState(st);
        const d = execTime(tk);
        const start = rel > tk.prevFinish ? rel : tk.prevFinish;
        const finish = start + d;
        tk.prevFinish = finish;
        const lat = finish - rel;
        if (lat > tk.spec.period) tk.misses++;
        tk.releases++; tk.sumLat += lat;
        if (lat > tk.maxLat) tk.maxLat = lat;
        tk.pending.push([finish, out]);
        tk.next += tk.spec.period;
      }
    }
  }

  // --- plant turevleri
  const k1 = new Float64Array(NSTATE), k2 = new Float64Array(NSTATE),
        k3 = new Float64Array(NSTATE), k4 = new Float64Array(NSTATE),
        ytmp = new Float64Array(NSTATE);
  let lastHook = 0, lastTWt = 0, lastTMot = 0, lastTens = 0;

  function deriv(yy, dy) {
    const x = yy[IX], v = yy[IV], w = yy[IW], z = yy[IZ], i = yy[II];
    const s = payout(x, b), sdot = dpayout(x, b) * v;
    const d = s - yy[ISD] - z;
    const rel = sdot - p.drumRadius * w;
    const num = p.kCable * d + p.cCable * rel + (p.cCable * kShockEff / cShock) * z;
    let tens = num / (1 + p.cCable / cShock);
    if (tens < 0) tens = 0;
    const zdot = (tens - kShockEff * z) / cShock;
    const dsdx = dpayout(x, b);
    const fHook = tens * dsdx;
    const fRoll = v > 0 ? p.rollResist : 0;
    dy[IX] = v;
    dy[IV] = (p.thrust - fHook - fRoll) / p.mass;
    dy[IZ] = zdot;
    const emf = p.kt * w;
    let vApp;
    if (!ctrl.motorEnabled) { dy[II] = -i / 2.0e-3; vApp = 0; }
    else {
      vApp = Math.max(0, Math.min(yy[IVB], emf - ctrl.uVolt));
      dy[II] = ((emf - vApp) - p.rPh * i) / p.lPh;
    }
    const ripple = p.rippleAmp !== 0 ? 1 + p.rippleAmp * Math.sin(p.rippleOrder * yy[ITH]) : 1;
    const tMot = p.kt * i * ripple;
    const tWt = p.kWt * w * Math.abs(w);
    const tFric = p.drumFriction * w;
    dy[ITH] = w;
    dy[ISD] = p.drumRadius * w;
    dy[IW] = (tens * p.drumRadius - tWt - tMot - tFric) / p.drumInertia;
    const vb = Math.max(50, yy[IVB]);
    const pIn = ctrl.motorEnabled ? vApp * i : 0;
    const pChop = vb > p.vChop ? (vb - p.vChop) * vb / p.rChop : 0;
    dy[IVB] = (pIn - pChop) / (cEff * vb);
    dy[IEWT] = tWt * w;
    dy[IEMOT] = ctrl.motorEnabled ? emf * i : 0;
    dy[IECH] = pChop;
    dy[IERL] = p.rPh * i * i;
    dy[IEDMP] = p.cCable * Math.pow(rel - zdot, 2) + cShock * zdot * zdot;
    dy[IETHR] = p.thrust * v;
    dy[IEROLL] = fRoll * v;
    dy[IEFR] = tFric * w;
    lastHook = fHook; lastTWt = tWt; lastTMot = tMot; lastTens = tens;
  }

  function rk4(dt) {
    deriv(y, k1);
    for (let j = 0; j < NSTATE; j++) ytmp[j] = y[j] + 0.5 * dt * k1[j];
    deriv(ytmp, k2);
    for (let j = 0; j < NSTATE; j++) ytmp[j] = y[j] + 0.5 * dt * k2[j];
    deriv(ytmp, k3);
    for (let j = 0; j < NSTATE; j++) ytmp[j] = y[j] + dt * k3[j];
    deriv(ytmp, k4);
    const s6 = dt / 6;
    for (let j = 0; j < NSTATE; j++) y[j] += s6 * (k1[j] + 2 * k2[j] + 2 * k3[j] + k4[j]);
    if (y[II] > p.iMax) y[II] = p.iMax; else if (y[II] < -p.iMax) y[II] = -p.iMax;
    if (y[IVB] < 50) y[IVB] = 50;
    deriv(y, k1);
  }

  // --- ana dongu
  const dt = p.baseDt, deckPeriod = 1 / p.deckRate;
  let t = 0, nextDeck = 0, n = 0, pcsTripped = false;
  let peakHook = 0, peakA = 0, sq = 0, nsq = 0, isq = 0, ierrMax = 0;
  let vbusMax = p.vNom, vbusMin = p.vNom;
  const tr = { t: [], x: [], v: [], vref: [], hook: [], w: [], twt: [], tmot: [], vbus: [], i: [], deg: [], g: [] };
  const events = { watchdog: [], degraded: [], drops: [], pcs: [] };
  let degStart = -1;

  while (t < p.tMax_) {
    if (y[IV] <= 0) break;
    if (t + 1e-12 >= nextDeck) {
      const outage = p.netOutageStart >= 0 && t >= p.netOutageStart &&
                     t < p.netOutageStart + p.netOutageDur;
      deck.send(t, [y[IX], y[IV]], outage);
      nextDeck += deckPeriod;
    }
    if (!pcsTripped && p.pcsLossTime >= 0 && t >= p.pcsLossTime) {
      cEff = p.pcsCAfter; pcsTripped = true; events.pcs.push(t);
    }
    const wasDeg = ctrl.degraded;
    schedStep(t);
    if (!wasDeg && ctrl.degraded) { degStart = t; events.watchdog.push(t); }
    if (wasDeg && !ctrl.degraded && degStart >= 0) { events.degraded.push([degStart, t]); degStart = -1; }
    rk4(dt);
    t += dt; n++;

    const hook = lastHook;
    if (hook > peakHook) peakHook = hook;
    const a = (hook + (y[IV] > 0 ? p.rollResist : 0) - p.thrust) / p.mass;
    if (a > peakA) peakA = a;
    if (y[IX] > X_ENGAGE) {
      const e = y[IV] - ctrl.vRef; sq += e * e; nsq++;
      const ie = ctrl.iCmd - y[II]; isq += ie * ie;
      if (Math.abs(ie) > ierrMax) ierrMax = Math.abs(ie);
    }
    if (y[IVB] > vbusMax) vbusMax = y[IVB];
    if (y[IVB] < vbusMin) vbusMin = y[IVB];

    if (n % traceEvery === 0) {
      tr.t.push(t); tr.x.push(y[IX]); tr.v.push(y[IV]); tr.vref.push(ctrl.vRef);
      tr.hook.push(hook); tr.w.push(y[IW]); tr.twt.push(lastTWt); tr.tmot.push(lastTMot);
      tr.vbus.push(y[IVB]); tr.i.push(y[II]); tr.deg.push(ctrl.degraded ? 1 : 0);
      tr.g.push(a / 9.81);
    }
  }
  if (degStart >= 0) events.degraded.push([degStart, t]);

  // --- enerji
  const ke0 = 0.5 * p.mass * p.entrySpeed * p.entrySpeed;
  const ke = 0.5 * p.mass * y[IV] * y[IV];
  const rot = 0.5 * p.drumInertia * y[IW] * y[IW];
  const dEl = payout(y[IX], b) - y[ISD] - y[IZ];
  const spring = 0.5 * p.kCable * Math.pow(Math.max(0, dEl), 2) + 0.5 * kShockEff * y[IZ] * y[IZ];
  const diss = y[IEWT] + y[IEMOT] + y[IEDMP] + y[IEROLL] + y[IEFR];
  const energy = {
    ke0, ke, rot, spring,
    eWt: y[IEWT], eMot: y[IEMOT], eChop: y[IECH], eRloss: y[IERL],
    eDamp: y[IEDMP], eThrust: y[IETHR], eRoll: y[IEROLL], eFric: y[IEFR],
    twisterShare: diss > 0 ? y[IEWT] / diss : 0,
    motorShare: diss > 0 ? y[IEMOT] / diss : 0,
    balanceErr: ((ke0 + y[IETHR]) - (ke + rot + spring + diss)) / Math.max(1, ke0),
  };

  const taskReport = {};
  let misses = 0;
  for (const tk of tasks) {
    misses += tk.misses;
    taskReport[tk.name] = {
      releases: tk.releases, misses: tk.misses, skipped: tk.skipped,
      maxLatUs: tk.maxLat * 1e6,
      meanLatUs: tk.releases ? tk.sumLat / tk.releases * 1e6 : 0,
    };
  }

  const metrics = {
    stopped: y[IV] <= 0, runout: y[IX], tStop: t,
    peakHook, peakG: peakA / 9.81,
    trackRms: nsq ? Math.sqrt(sq / nsq) : 0,
    iRms: nsq ? Math.sqrt(isq / nsq) : 0, iErrMax: ierrMax,
    vbusMax, vbusMin,
    deckMaxStaleMs: deck.maxStale * 1e3, deckDrops: deck.drops, deckSent: deck.sent,
    watchdogEvents: ctrl.watchdogEvents, bin: ctrl.bin, runoutTarget: ctrl.runoutTarget,
    deadlineMisses: misses,
  };
  const checks = [
    { key: 'runout', label: 'Runout', val: metrics.runout, lim: p.limRunout, unit: 'm', ok: metrics.runout <= p.limRunout && metrics.stopped },
    { key: 'hook', label: 'Tepe kanca yükü', val: metrics.peakHook / 1e3, lim: p.limHook / 1e3, unit: 'kN', ok: metrics.peakHook <= p.limHook },
    { key: 'g', label: 'Tepe yavaşlama', val: metrics.peakG, lim: p.limPeakG, unit: 'g', ok: metrics.peakG <= p.limPeakG },
    { key: 'rms', label: 'Hız izleme RMS', val: metrics.trackRms, lim: p.limRms, unit: 'm/s', ok: metrics.trackRms <= p.limRms },
    { key: 'vbus', label: 'DC bara tepe', val: metrics.vbusMax, lim: p.limVbus, unit: 'V', ok: metrics.vbusMax <= p.limVbus },
  ];
  metrics.pass = metrics.stopped && checks.every(c => c.ok);
  return { metrics, energy, trace: tr, events, tasks: taskReport, checks, drops: deck.dropTimes };
}

export { defaults, binOf, gainsOf, payout, dpayout, X_ENGAGE, X_RAMP };
