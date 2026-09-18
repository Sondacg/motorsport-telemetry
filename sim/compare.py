#!/usr/bin/env python3
"""Compare traction control laws against the plant, on and off design.

    python sim/compare.py

THE POINT OF THE OFF-DESIGN COLUMN. Every controller tuned at a given grip
level looks competent at that grip level; a table with one column is not a
comparison, it is four separate demonstrations. So each law is configured once
against mu = 1.45 and then run, untouched, against mu = 1.00 — a cooler tyre, a
damper surface, a track that rubbered in differently than expected.

Nothing about the car tells the controller this happened. That is the test.
"""

import numpy as np

import vehicle
import controllers

DT = 1e-3
DURATION = 4.0
V_EXIT = vehicle.V_EXIT_KPH / 3.6
V_TARGET = vehicle.V_TARGET_KPH

MU_DESIGN = 1.45
MU_DEGRADED = 1.00
SETTLE_AFTER = 0.30  # s; ignore the initial transient when scoring tracking


def run(controller, mu, tau=None):
    car = vehicle.Vehicle(mu_peak=mu)
    if tau is not None:
        car.throttle_tau = tau
    if hasattr(controller, "reset"):
        controller.reset()
    fn = lambda t, state, kappa: controller(t, state, kappa, car, DT)
    return vehicle.simulate(car, fn, duration=DURATION, dt=DT, v0=V_EXIT)


def score(result, target):
    """Four numbers, each answering a different question about the same run."""
    after = result["t"] >= SETTLE_AFTER
    error = result["kappa"][after] - target
    return {
        "t100": vehicle.time_to(result, V_TARGET),
        "peak": float(result["kappa"].max()),
        "rms": float(np.sqrt(np.mean(error ** 2))),
        # Mean absolute change in the command per sample: how hard the actuator
        # is being worked. A law that wins on lap time by hammering the throttle
        # a thousand times a second has not won.
        "chatter": float(np.mean(np.abs(np.diff(result["throttle"])))),
    }


def main():
    reference = vehicle.Vehicle(mu_peak=MU_DESIGN)
    target = vehicle.peak_slip(reference)
    for c in controllers.ALL:
        if hasattr(c, "target"):
            c.target = target

    print(f"corner exit at {vehicle.V_EXIT_KPH:.0f} km/h, slip target "
          f"kappa = {target:.3f}")
    print(f"designed against mu = {MU_DESIGN}, then run at mu = {MU_DEGRADED} "
          "with no retuning\n")

    results, rows = {}, []
    for c in controllers.ALL:
        name = getattr(c, "name", c.__class__.__name__)
        on = run(c, MU_DESIGN)
        off = run(c, MU_DEGRADED)
        results[name] = (on, off)
        rows.append((name, score(on, target), score(off, target)))

    head = f"{'':20}|{'  mu = 1.45 (design)':^34}|{'  mu = 1.00 (off design)':^34}"
    sub = (f"{'':20}|{'to 100':>9}{'peak k':>9}{'rms e':>8}{'chatter':>8}"
           f"|{'to 100':>9}{'peak k':>9}{'rms e':>8}{'chatter':>8}")
    print(head)
    print(sub)
    print("-" * len(sub))
    for name, a, b in rows:
        print(f"{name:20}|{a['t100']:>8.2f}s{a['peak']:>9.3f}{a['rms']:>8.3f}"
              f"{a['chatter']:>8.4f}"
              f"|{b['t100']:>8.2f}s{b['peak']:>9.3f}{b['rms']:>8.3f}"
              f"{b['chatter']:>8.4f}")

    print("\nDegradation from design to off-design, in time to 100 km/h:")
    for name, a, b in rows:
        delta = b["t100"] - a["t100"]
        print(f"  {name:20} {delta:+.3f}s")

    # Every law overshoots to roughly the same place off design, which says the
    # limit is not the law. Sweep the one thing they all sit behind.
    print("\nPeak slip against actuator time constant, mu = 1.00:")
    taus = [0.005, 0.02, 0.04, 0.08, 0.15]
    sweep = {getattr(c, "name", ""): [] for c in controllers.ALL[1:]}
    print(f"  {'tau (ms)':>9}" + "".join(f"{n:>19}" for n in sweep))
    for tau in taus:
        cells = ""
        for c in controllers.ALL[1:]:
            peak = float(run(c, MU_DEGRADED, tau)["kappa"].max())
            sweep[getattr(c, "name", "")].append(peak)
            cells += f"{peak:>19.3f}"
        print(f"  {tau*1000:>9.0f}{cells}")

    spread = max(v[-2] for v in sweep.values()) - min(v[-2] for v in sweep.values())
    span = max(v[-1] for v in sweep.values()) - min(v[0] for v in sweep.values())
    print(f"\n  choice of control law moves peak slip by {spread:.3f}")
    print(f"  actuator bandwidth moves it by       {span:.3f}")
    print("  The actuator is the design lever. The control law is a detail.")

    try:
        import plot_compare
        plot_compare.draw(results, target, (taus, sweep))
    except ImportError:
        pass


if __name__ == "__main__":
    main()
