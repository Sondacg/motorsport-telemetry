# Design review — traction control, phase 2

Status: **proposed**, not implemented on target.
Everything below is reproducible from `sim/`; every number names the script
that produced it.

---

## 1. Requirement

On corner exit at full throttle, hold longitudinal slip near the peak of the
tyre curve so that the driven axle delivers close to the force it is capable
of, without relying on the driver to modulate the pedal.

The plant model prices what this is worth (`sim/vehicle.py`):

| corner exit, 54 km/h | to 100 km/h | peak slip |
|---|---|---|
| full throttle, no control | 1.71 s | 0.735 |
| slip held at the peak (oracle) | 1.61 s | 0.136 |

**0.10 s per corner exit.** Over eight slow corners that is most of a second a
lap, and it is the entire budget this design has to recover. Anything that
costs more than it returns is not worth shipping.

---

## 2. Scope and assumptions

Longitudinal axis only. The model has no lateral dynamics, so it cannot show
the effect that matters most in a real corner — that slip used longitudinally
is not available laterally. This is the single largest gap between the model
and the car, and it biases every result here towards under-valuing the
controller.

| assumption | value | where it comes from |
|---|---|---|
| Rear-wheel drive, one driven axle lumped | — | scope |
| Tyre | Magic Formula, peak μ 1.45, peak at κ = 0.133 | fitted to fall ~12% by κ = 0.4 |
| Actuator | first-order lag, τ = 80 ms | throttle body; spark cut would be faster |
| Control loop | 100 Hz, zero-order hold | a task on a timer, not the solver rate |
| Road speed | known exactly | **false on a car — see §8** |

Off-design condition is μ = 1.00: a cooler tyre, a damper surface. Every law is
configured once against 1.45 and then run untouched at 1.00. A comparison with
only the design column is not a comparison, it is several separate
demonstrations.

---

## 3. Candidates

1. **Threshold cut** — shut the throttle above the slip target, restore below.
   What gets written when nobody asks for a design.
2. **PI with anti-windup** — regulate slip error. The obvious answer.
3. **Sliding mode with equivalent control** — model computes the throttle that
   holds the wheel where it is; a saturated switching term covers what the
   model got wrong.

---

## 4. What the comparison found

### 4.1 Lap time does not separate them

All three reach 100 km/h within 0.01 s of each other. That is not a tie between
the laws, it is the tyre: held near peak slip the car is at the traction limit
and no control law finds more. **Lap time is therefore not a discriminator** and
the comparison has to move to peak slip and actuator effort.

### 4.2 The actuator dominates the law by twenty to one

Peak slip at μ = 1.00, sweeping the actuator time constant (`sim/compare.py`):

| actuator τ | bang-bang | PI | sliding mode |
|---|---|---|---|
| 5 ms | 0.380 | 0.357 | 0.353 |
| 40 ms | 0.557 | 0.557 | 0.515 |
| 80 ms | 0.751 | 0.751 | 0.721 |
| 150 ms | 0.957 | 0.957 | 0.941 |

Choice of law moves peak slip by **0.03**. Actuator bandwidth moves it by
**0.60**.

> **The first recommendation of this review is not a control law.** It is to
> take the torque path off the throttle body and onto spark or fuel cut. That
> single change is worth more than any amount of sophistication in the law
> sitting behind it.

### 4.3 The first gains were seven times over the stability boundary

The initial comparison showed all three laws limit-cycling. That was not a
property of the laws: the PI gain had been chosen by taste. Sweeping gain
against actuator lag and counting crossings of the target
(`sim/stability.py`, at μ = 1.00):

| actuator τ | largest gain without limit cycle |
|---|---|
| 5 ms | 4 |
| 20 ms | 3 |
| 80 ms | **2** |
| 150 ms | 2 |

The comparison had been run at **Kp = 14** against a boundary of **2**.

### 4.4 And at a defensible gain, the PI stops working

Re-running with Kp = 1 — half the boundary, a gain margin of 2:

| μ = 1.00 | peak slip | to 100 km/h |
|---|---|---|
| no control | 0.969 | 2.61 s |
| PI, Kp = 1 (margin 2) | **0.966** | 2.51 s |
| bang-bang | 0.751 | 2.38 s |
| sliding mode | **0.721** | 2.37 s |

The PI is now stable and useless: its peak slip is within 0.003 of no control
at all. **At an 80 ms actuator the PI cannot be both stable and quick** — the
gain that catches the transient is the gain that rings.

---

## 5. Decision

**Sliding mode with equivalent control.**

Not because it is the most sophisticated, and not on lap time, which does not
separate the candidates. Because of §4.4: the PI derives its authority from
loop gain, and loop gain is exactly what the actuator lag will not let it have.
Sliding mode derives most of its authority from the model — the equivalent
control term already knows roughly what throttle the wheel wants — and uses the
switching term only to cover the error. It is not forced into the same trade.

Bang-bang is within 0.03 of it on peak slip and is simpler. It is rejected on
actuator effort: 0.0135 against 0.0107 mean command change per sample, on a
component whose bandwidth §4.2 already identifies as the binding constraint.

Accepted cost: sliding mode needs a plant model on the target, which is code
and calibration that bang-bang does not need.

---

## 6. Margins

| quantity | boundary | chosen | margin |
|---|---|---|---|
| PI proportional gain at τ = 80 ms | 2 | 1 | 2× |
| Friction departure from design | — | works at μ = 1.00 from a 1.45 design | 31% |

The friction margin is the one that matters and it is not yet a margin, it is a
single off-design point. §7 turns it into one.

---

## 7. Validation plan

1. **Parameter sweep, not a point.** μ from 0.7 to 1.6, tyre peak location
   ±30%, mass ±10%, actuator τ from 5 to 150 ms. Pass criterion: peak slip
   below 0.35 and no limit cycle anywhere in the box.
2. **Against recorded data.** The telemetry stack already reads per-wheel slip
   from a real session (`AssettoCorsaSource.h`). Replay a recorded corner exit
   through the plant and compare predicted slip against measured. This is the
   only step here that can falsify the model rather than exercise it.
3. **On target.** Same law, generated or hand-written C on the STM32, driven by
   the same recorded inputs. Bit-comparison against the Python where the
   arithmetic allows, tolerance-comparison where it does not.
4. **In the loop.** The phase 3 HIL bench, with the controller on hardware and
   the plant in the loop over CAN-FD.

---

## 8. Open items and risks

**Road speed is assumed known.** Slip ratio here divides by a road speed the
simulation knows exactly. A car does not: it has driven and undriven wheel
speeds and an accelerometer, and under a traction event the driven wheels are
by definition lying. An estimator is required before any of this runs on a car,
and its error feeds directly into the controlled variable. *Next work package.*

**No lateral dynamics.** See §2. Every result here understates the value of the
controller, because the cost of excess longitudinal slip includes lateral grip
the model cannot represent.

**The tyre is invented.** Coefficients were chosen to produce a realistic
shape, not fitted to a real tyre. §7.2 is what turns this from a plausible
curve into a validated one.

**Peak slip is not constant.** The target is fixed at 0.133, the peak for this
tyre at this load. Real peak location moves with load, temperature and wear.
Out of scope here; a peak-seeking outer loop is the usual answer.

---

## 9. Reproducing

```bash
python sim/vehicle.py      # the plant, and what wheelspin costs
python sim/compare.py      # three laws, on and off design, actuator sweep
python sim/stability.py    # gain against actuator lag, limit-cycle boundary
```
