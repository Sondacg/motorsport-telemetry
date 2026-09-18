#!/usr/bin/env python3
"""Where does the PI go into limit cycle, and how far are we from it?

    python sim/stability.py

The comparison left a loose end: all three laws oscillated at an 80 ms
actuator. That is the classic symptom of loop gain too high for the delay in
the loop, and it is not a property of the law — it is a property of the gain
that was picked without reference to the actuator.

This sweeps proportional gain against actuator time constant and finds, for
each actuator, the gain at which sustained oscillation begins. The result is a
stability boundary, and a boundary is what lets a design claim a margin rather
than assert that it feels fine.
"""

import numpy as np

import vehicle
import controllers

DT = 1e-3
DURATION = 3.0
WINDOW = (0.3, 1.5)   # s; after the launch transient, before the rev limiter
CROSSING_LIMIT = 8    # crossings of the target in that window = limit cycle

TAUS = [0.005, 0.01, 0.02, 0.04, 0.08, 0.15]
GAINS = [0.5, 1, 2, 3, 4, 6, 8, 11, 14, 18, 24, 32]


def oscillation(kp: float, tau: float, mu: float = 1.00) -> int:
    """How many times slip crosses its target after the launch transient.

    Peak-to-peak slip was the obvious metric and the wrong one: the car is
    still accelerating through this window, so slip moves for honest reasons
    and every gain looked unstable. Counting crossings asks the question that
    was actually meant — is it ringing, or is it converging?
    """
    car = vehicle.Vehicle(mu_peak=mu)
    car.throttle_tau = tau
    ctrl = controllers.PI(target=vehicle.peak_slip(car), kp=kp, ki=kp * 3.2)
    ctrl.reset()
    result = vehicle.simulate(
        car, lambda t, s, k: ctrl(t, s, k, car, DT),
        duration=DURATION, dt=DT, v0=vehicle.V_EXIT_KPH / 3.6)

    inside = (result["t"] >= WINDOW[0]) & (result["t"] <= WINDOW[1])
    error = result["kappa"][inside] - ctrl.target
    return int(np.count_nonzero(np.diff(np.signbit(error))))


def boundary():
    """Largest gain that does not sustain oscillation, per actuator.

    Swept at mu = 1.00, not at the design grip: at 1.45 the car reaches the rev
    limiter inside the measurement window and slip simply sits below target,
    crossing nothing. The boundary has to be measured where the loop is actually
    working.
    """
    limits, grid = {}, {}
    for tau in TAUS:
        amps = [oscillation(kp, tau) for kp in GAINS]
        grid[tau] = amps
        stable = [kp for kp, a in zip(GAINS, amps) if a < CROSSING_LIMIT]
        limits[tau] = max(stable) if stable else 0.0
    return limits, grid


def main():
    limits, grid = boundary()

    print(f"Crossings of the slip target between {WINDOW[0]} s and "
          f"{WINDOW[1]} s. 'osc' is a limit cycle.\n")
    print(f"{'tau (ms)':>9}" + "".join(f"{kp:>7.0f}" for kp in GAINS))
    for tau in TAUS:
        cells = "".join(
            (f"{a:>7d}" if a < CROSSING_LIMIT else f"{'osc':>7}")
            for a in grid[tau])
        print(f"{tau*1000:>9.0f}{cells}")

    print(f"\n{'tau (ms)':>9} {'max stable Kp':>15}")
    for tau in TAUS:
        print(f"{tau*1000:>9.0f} {limits[tau]:>15.1f}")

    chosen = controllers.PI().kp
    at80 = limits.get(0.08, 0.0)
    print(f"\nThe comparison ran Kp = {chosen:.0f} at tau = 80 ms, where the "
          f"boundary is {at80:.0f}.")
    if chosen > at80:
        print("That is why every law oscillated: the gain was above the "
              "boundary, not\nbelow it. The fault was the tuning, not the "
              "choice of law.")
        print(f"A gain margin of 2 at this actuator means Kp = {at80 / 2:.1f}.")

    try:
        import plot_stability
        plot_stability.draw(TAUS, GAINS, grid, limits, CROSSING_LIMIT)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
