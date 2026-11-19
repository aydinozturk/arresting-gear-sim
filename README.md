# Arresting Gear Sim

*English · [Türkçe](README.tr.md)*

A closed-loop simulation of a carrier aircraft **arresting gear**, written to answer a
software question rather than a physics one: **which real-time properties actually matter,
and which ones don't?**

The control loop does not run as a continuous-time idealisation. It runs the way real-time
code runs — four periodic tasks at four different rates, each with its own execution time,
jitter and overrun behaviour, reading sensors over a link with latency, jitter and packet
loss. All of that is injectable and seeded, so every "non-deterministic" run reproduces
exactly.

Pure Python standard library. **No dependencies, no build step.**

> **These are not real AAG numbers.** The model is built from publicly described
> architecture, not from any system data. Every numeric parameter in
> [`aag/params.py`](aag/params.py) is an assumption, marked as such. Read the results as
> *relative sensitivities* of this architecture, never as validation of a real system.

---

## Quick start

```bash
python3 run_arrest.py        # one arrest, text report + CSV trace
```

```bash
python3 tests/selfcheck.py   # energy balance, step convergence, determinism
```

```bash
python3 run_scenarios.py     # ten named fault scenarios side by side
```

```bash
python3 sweeps/sweep_timing.py   # the full timing/network/power sweep suite (~15 min)
```

For the interactive bench, open [`ui/simulator.html`](ui/simulator.html) in a browser —
single file, works offline, nothing to install.

---

## What it models

```
aircraft (m, v) ── deck pendant geometry s(x)=2(√(x²+B²)−B) ── elastic cable
   └─ weight-scheduled shock absorber ── drum (J)
        ├─ water twister   T = k·ω|ω|        (≈70 % of the energy)
        └─ induction motor                   (fine control, final stop)
              └─ shared PCS: DC bus + capacitor bank + braking chopper
```

Cable payout is nonlinear in travel, so the same hook force needs very different cable
tension early and late in the run. The drum shaft carries both a hydrodynamic brake and a
controlled machine, and both feed one shared power conditioning system.

Control, as four discrete tasks:

| Task | Rate | Job |
|---|---|---|
| `supervisor` | 100 Hz | weight × speed gain bin, watchdog, degraded mode |
| `trajectory` | 500 Hz | velocity reference `v_ref(x)` |
| `outer` | 1 kHz | shaft torque command (feedforward + PI) |
| `inner` | 10 kHz | motor current control (PI) |

Each task reads its inputs at release and applies its output at
`release + execution_time`. Jobs of one task run **in sequence**, and what happens when a
job overruns its period is an explicit policy (`skip` or `queue`) — which turns out to
matter more than the execution time itself.

### Nominal operating point

22 t at 65 m/s: runout **97.7 m**, peak hook load **804 kN**, peak deceleration **3.29 g**,
velocity tracking RMS **2.19 m/s**, water twister share **70.2 %**, energy balance closes
to **0.000 %**, and halving the integration step moves every metric by less than 0.01 %.

---

## What the sweeps found

Eighteen sweeps, each perturbing one path and finding where the acceptance criteria break.
Full write-up (Turkish): [`docs/rt-work-items.md`](docs/rt-work-items.md).

### 1. The overrun policy matters more than the WCET

Current loop, 100 µs period, execution time swept:

| WCET | `queue` | `skip` |
|---|---|---|
| 95 µs | 97.7 m · 3.29 g (14 641 missed deadlines) | 97.7 m · 3.29 g |
| **120 µs** | **never stops · 8.42 g · 1910 kN** | 97.7 m · 3.29 g |
| 400 µs | 137 m · 5.97 g | 97.7 m · 3.30 g |

With an unbounded job queue, the moment execution time exceeds the period the input-output
delay grows by 20 µs per job and the arrest reaches mechanical damage levels. With
skip-if-busy, a 4× overrun is indistinguishable from nominal.

So the requirement is not "make the WCET small". It is **"define the overrun policy"**, and
write the acceptance criterion as `WCET < period`, not as "zero missed deadlines" — at 95 µs
the loop misses 14 641 deadlines and nothing happens.

### 2. Loop latency is harmless; the fallback is not

Watchdog threshold × network latency, cell = runout:

```
  wd / lat        0        5       10       20       30       50       80      120   [ms]
         5      98      98*  NOSTOP*  NOSTOP*  NOSTOP*  NOSTOP*  NOSTOP*  NOSTOP*
        20      98      98      98      98*  NOSTOP*  NOSTOP*  NOSTOP*  NOSTOP*
        80      98      98      98      98      98      98      98*  NOSTOP*
       160      98      98      98      98      98      98      98      98
```

*(runout in metres; `NOSTOP` = the aircraft never stopped inside the 6 s window, so the
figure would be censored; `*` = an acceptance criterion was violated. Four of the seven
watchdog rows shown.)*

The failure boundary is exactly the diagonal `latency ≥ watchdog threshold`. With the
watchdog at 160 ms, even 120 ms of pure latency changes nothing — the outer loop is
feedforward-dominated and the water twister provides strong passive feedback.

The real problem is what happens *after* the trip. The default degraded mode ramps motor
torque to zero, leaving only the twister — and `T ∝ ω²` cannot overcome steady thrust at low
speed, so **the aircraft never stops**. Estimating position and velocity from the local drum
encoder instead (inverting the payout geometry) keeps the loop closed with no dependency on
the deck network at all:

| Full network outage | torque ramp | encoder estimate |
|---|---|---|
| 400 ms | RMS 3.08 — fail | 97.7 m · RMS 2.29 — **pass** |
| 1000 ms | 107.8 m · 4.60 g — fail | 98.4 m · 3.43 g — **pass** |
| 1500 ms | 119.7 m — fail | 98.9 m · RMS 2.78 — **pass** |

A 1.5-second total blackout violates nothing once the safety path stops depending on the
network.

### 3. The shared power system is a single point of failure software cannot cover

Losing the capacitor bank at *any* point in the run means the aircraft does not stop
(409 m at 20 s and still rolling). It is the only scenario in the suite that fails
unconditionally. Detection, logging and a pre-recovery readiness check are the software's
job; the fix is architectural.

### Also measured

Jitter to ±20 ms, packet loss to 85 %, congestion bursts to 90 ms, outer-loop period to
32 ms, torque ripple to 60 %, deck sampling down to 25 Hz — none of these breaks a single
acceptance criterion on its own. They only do damage *through* the watchdog. The current
loop's period limit scales with its bandwidth (`T·ω_c ≲ 1.5`), not as an absolute number.

Weight estimation error is asymmetric: underestimating by 4000 kg fails, overestimating by
10 000 kg does not.

---

## Interactive bench

[`ui/simulator.html`](ui/simulator.html) is a single self-contained HTML file: top-down deck
view with the cable and the aircraft animated, live telemetry, acceptance criteria, a
real-time event strip (degraded intervals, watchdog trips, dropped packets) and four charts.
Every control re-runs the whole arrest in about 25 ms. Nine presets reproduce the findings
above with one click.

The browser engine ([`ui/engine.js`](ui/engine.js)) is a direct port of the Python model.
`node ui/verify.mjs` runs nine configurations through it and the numbers match the Python
model case for case.

---

## Self-checks

The sweep results are only worth reading if the model is sound, so `tests/selfcheck.py`
gates them:

- energy balance closes within 1 % (currently 0.000 %)
- halving the base step changes every metric by less than 1 %
- the same seed gives the same result — **in separate processes**, which caught a real bug:
  `hash()` on strings is salted per process, so the "deterministic" runs were not reproducible
- the fast integration mode agrees with the detailed one within 3 %
- the water twister takes 65–75 % of the energy, the one numeric target available

---

## Repository map

| Path | Contents |
|---|---|
| [`aag/params.py`](aag/params.py) | every parameter, each marked as an assumption |
| [`aag/plant.py`](aag/plant.py) | physics: aircraft, cable geometry, shock absorber, drum, twister, motor, PCS |
| [`aag/control.py`](aag/control.py) | the four discrete control tasks, gain bins, degraded mode |
| [`aag/rt.py`](aag/rt.py) | real-time scheduler and network layer — latency, jitter, overrun, packet loss |
| [`aag/sim.py`](aag/sim.py) | orchestration, metrics, energy accounting |
| [`sweeps/`](sweeps) | the sweep suites |
| [`ui/`](ui) | browser engine, interface template, build script |
| [`docs/design.md`](docs/design.md) | design document (Turkish) |
| [`docs/rt-work-items.md`](docs/rt-work-items.md) | **the actual output**: 14 real-time software work items, each tied to a measurement (Turkish) |
| [`out/`](out) | generated results — every table in the docs comes from these files |

## What the simulation cannot answer

WCET is an *input* here, not a measurement. CPU contention between tasks is not modelled, so
priority assignment and response-time analysis belong on the target hardware. The RTOS,
processor and bus are not modelled either — the published material this is based on does not
name them. And the "never stops" results depend on the assumption that thrust stays at full
power throughout the arrest.

## License

MIT — see [LICENSE](LICENSE).
