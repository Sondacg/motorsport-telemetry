#!/usr/bin/env python3
"""Longitudinal vehicle model: the plant a traction controller acts on.

Phase 2 designs a control law. This is the thing it will be designed against,
and it comes first: a controller tuned by feel on a real car is tuned against
whatever that car happened to do on the day, while a controller designed
against a model can be argued about, swept over parameters, and shown to hold
when the tyre is colder or the road is wetter than the day it was tuned.

THE MECHANISM, in one paragraph. A tyre does not transmit force because it
grips the road perfectly; it transmits force *because* it slips a little. Slip
ratio is how much faster the tyre surface is moving than the road:

    kappa = (omega * R - v) / max(v, eps)

Longitudinal force rises steeply with kappa, peaks somewhere near 0.1-0.2 on a
racing tyre, and then FALLS AWAY. That falling region is the whole problem. Past
the peak, more wheelspin produces less force, so the wheel accelerates harder,
which produces even less force. It runs away. Traction control exists to hold
the tyre on the near side of that peak.

Run this file to see it happen, and to get the lap-stopwatch version of the
cost: how much slower full throttle is than perfect throttle.

    python sim/vehicle.py
"""

from dataclasses import dataclass, field
import math

import numpy as np


@dataclass
class Vehicle:
    """A rear-wheel-drive car, longitudinal axis only.

    Numbers are GT-class order of magnitude. They are not any particular car,
    and that is fine: the point of the model is the shape of the behaviour, and
    a controller that only works for one exact parameter set is not a
    controller, it is a coincidence.
    """

    mass: float = 1200.0          # kg
    wheel_radius: float = 0.33    # m
    wheel_inertia: float = 1.2    # kg m^2, both driven wheels lumped
    wheelbase: float = 2.60       # m
    cg_height: float = 0.30       # m
    rear_weight_fraction: float = 0.55

    # Aerodynamics and rolling resistance.
    drag_area: float = 1.00       # Cd * A, m^2
    air_density: float = 1.225    # kg/m^3
    rolling_coefficient: float = 0.015

    # Magic Formula (Pacejka) longitudinal coefficients. D is the peak friction
    # coefficient; B sets how steeply force builds with slip; C and E shape the
    # curve after the peak — E is what makes it fall away rather than plateau.
    # These were chosen to give a peak near kappa = 0.13 and roughly 12% less
    # force by kappa = 0.4. The fall-off is the point: a curve that plateaus
    # after the peak has no runaway in it, and a traction controller built
    # against a plateau would have nothing to do.
    mu_peak: float = 1.45
    tyre_B: float = 12.0
    tyre_C: float = 1.45
    tyre_E: float = -0.50

    # Driveline: a torque curve at the crank, multiplied to the wheel.
    gear_ratio: float = 2.80
    final_drive: float = 3.50
    driveline_efficiency: float = 0.92
    rev_limit: float = 8500.0     # rpm

    # A torque request does not arrive instantly. Eighty milliseconds is a
    # throttle body; spark or fuel cut would be faster, but designing against
    # the slower actuator is the honest way round.
    throttle_tau: float = 0.08    # s
    gravity: float = 9.81

    def tyre_force(self, kappa: float, normal_load: float) -> float:
        """Longitudinal tyre force for a slip ratio and a vertical load.

        The sign of kappa carries through, so braking works without a separate
        branch. Force scales with load, which is why weight transfer matters:
        accelerating presses the driven axle down and buys grip.
        """
        B, C, D, E = self.tyre_B, self.tyre_C, self.mu_peak, self.tyre_E
        Bk = B * kappa
        return normal_load * D * math.sin(
            C * math.atan(Bk - E * (Bk - math.atan(Bk)))
        )

    def rear_normal_load(self, accel: float) -> float:
        """Static rear load plus the transfer caused by accelerating."""
        static = self.mass * self.gravity * self.rear_weight_fraction
        transfer = self.mass * accel * self.cg_height / self.wheelbase
        return max(0.0, static + transfer)

    def engine_torque(self, wheel_omega: float, throttle: float) -> float:
        """Crank torque through the gearbox, as torque at the driven wheels.

        A flat-ish curve that tails off towards the limiter. Crude, but the
        controller is not being asked to exploit the torque curve — only to
        avoid asking the tyre for more than it can give.
        """
        ratio = self.gear_ratio * self.final_drive
        rpm = abs(wheel_omega) * ratio * 60.0 / (2.0 * math.pi)
        if rpm >= self.rev_limit:
            return 0.0
        # Peak near mid-range, softening towards the limiter.
        shape = 1.0 - 0.35 * (rpm / self.rev_limit) ** 2
        crank = 480.0 * shape
        return max(0.0, throttle) * crank * ratio * self.driveline_efficiency

    def resistance(self, v: float) -> float:
        """Drag and rolling resistance, always opposing motion."""
        drag = 0.5 * self.air_density * self.drag_area * v * v
        roll = self.rolling_coefficient * self.mass * self.gravity
        return math.copysign(drag + roll, v) if v != 0.0 else 0.0


SLIP_EPS = 0.5  # m/s; below this, slip ratio is meaningless and blows up


def slip_ratio(omega: float, v: float, radius: float) -> float:
    return (omega * radius - v) / max(abs(v), SLIP_EPS)


def derivatives(state, throttle_cmd: float, car: Vehicle):
    """State is [v, omega, u]: road speed, wheel speed, delivered throttle.

    Two bodies, one contact patch. The tyre force appears with opposite signs
    in the two equations, which is the entire coupling: torque that does not
    reach the road through the tyre goes into spinning the wheel up instead.
    """
    v, omega, u = state
    kappa = slip_ratio(omega, v, car.wheel_radius)

    # Load transfer depends on acceleration, which depends on the force that
    # the load itself sets. Two passes converge to well inside the accuracy of
    # everything else here.
    accel, Fx = 0.0, 0.0
    for _ in range(2):
        Fx = car.tyre_force(kappa, car.rear_normal_load(accel))
        accel = (Fx - car.resistance(v)) / car.mass

    omega_dot = (car.engine_torque(omega, u)
                 - Fx * car.wheel_radius) / car.wheel_inertia
    u_dot = (throttle_cmd - u) / car.throttle_tau
    return np.array([accel, omega_dot, u_dot]), kappa, Fx


CONTROL_HZ = 100.0   # the loop rate a traction controller actually gets


def simulate(car: Vehicle, throttle_fn, duration=4.0, dt=1e-3, v0=15.0,
             control_hz=CONTROL_HZ):
    """Fixed-step RK4, with the controller sampled and held at its own rate.

    Two rates on purpose. The plant is integrated finely; the controller is
    called every 1/control_hz and its command is held between calls, because
    that is what a task on a timer does. Running a controller at the
    integration rate flatters it — it hides exactly the lag that decides
    whether a law is stable on real hardware.
    """
    n = int(duration / dt)
    t = np.zeros(n)
    v = np.zeros(n)
    w = np.zeros(n)
    k = np.zeros(n)
    fx = np.zeros(n)
    thr = np.zeros(n)

    state = np.array([v0, v0 / car.wheel_radius, 1.0])  # rolling, throttle open
    every = max(1, int(round(1.0 / (control_hz * dt))))
    u = 1.0

    for i in range(n):
        time = i * dt
        kappa = slip_ratio(state[1], state[0], car.wheel_radius)
        if i % every == 0:
            u = float(np.clip(throttle_fn(time, state[:2], kappa), 0.0, 1.0))

        t[i], v[i], w[i], thr[i] = time, state[0], state[1], u
        d1, k[i], fx[i] = derivatives(state, u, car)
        d2, _, _ = derivatives(state + 0.5 * dt * d1, u, car)
        d3, _, _ = derivatives(state + 0.5 * dt * d2, u, car)
        d4, _, _ = derivatives(state + dt * d3, u, car)
        state = state + (dt / 6.0) * (d1 + 2 * d2 + 2 * d3 + d4)
        state[1] = max(state[1], 0.0)
        state[2] = min(max(state[2], 0.0), 1.0)

    return {"t": t, "v": v, "omega": w, "kappa": k, "fx": fx, "throttle": thr}


def peak_slip(car: Vehicle) -> float:
    """Where the tyre curve peaks — the slip a controller should aim for."""
    grid = np.linspace(0.0, 0.6, 2001)
    forces = [car.tyre_force(k, 1.0) for k in grid]
    return float(grid[int(np.argmax(forces))])


def time_to(result, kph: float):
    target = kph / 3.6
    reached = np.where(result["v"] >= target)[0]
    return float(result["t"][reached[0]]) if len(reached) else float("nan")


V_EXIT_KPH = 54.0    # corner apex — where a traction controller earns its keep
V_TARGET_KPH = 100.0


def main():
    car = Vehicle()
    k_peak = peak_slip(car)

    # The scenario is a corner exit, not a standing start: it is the case that
    # matters, and slip ratio is ill-conditioned near zero road speed anyway.
    flat_out = simulate(car, lambda t, s, k: 1.0, v0=V_EXIT_KPH / 3.6)

    # An oracle that cannot be built: it knows the plant exactly and holds slip
    # at the peak. Not a controller — a bound, to say what perfect would cost.
    def oracle(t, state, kappa):
        return 1.0 if kappa < k_peak else 0.0

    ideal = simulate(car, oracle, v0=V_EXIT_KPH / 3.6)

    print(f"corner exit at {V_EXIT_KPH:.0f} km/h, full throttle")
    print(f"tyre peaks at slip ratio {k_peak:.3f}\n")
    print(f"{'':20} {'to 100 km/h':>12} {'peak slip':>11} {'mean slip':>11}")
    for name, r in (("full throttle", flat_out), ("slip held at peak", ideal)):
        print(f"{name:20} {time_to(r, V_TARGET_KPH):>11.2f}s "
              f"{r['kappa'].max():>11.3f} {r['kappa'].mean():>11.3f}")

    lost = time_to(flat_out, V_TARGET_KPH) - time_to(ideal, V_TARGET_KPH)
    print(f"\nwheelspin costs {lost:.2f}s "
          f"({100 * lost / time_to(ideal, V_TARGET_KPH):.0f}% slower)")
    print("That gap is the budget a traction controller has to recover.")

    try:
        import plot_plant
        plot_plant.draw(car, k_peak, flat_out, ideal)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
