#!/usr/bin/env python3
"""Estimating road speed, which the controller needs and the car cannot measure.

    python sim/estimator.py

Slip ratio divides by road speed. Every result so far used the speed the
simulation happened to know. A car does not know it: it has wheel speed
sensors and an accelerometer, and during a traction event the driven wheels
are, by definition, the ones that are lying.

Three ways to answer it, and the first two are the instructive ones.

DRIVEN WHEEL. Take road speed from the wheel you are controlling. It is
circular, and it fails in exactly the situation the controller exists for: the
wheel spins up, the estimate rises with it, the apparent slip stays near zero,
and the controller sees no reason to act. A traction controller built on this
does nothing precisely when it is needed.

UNDRIVEN WHEEL. On a rear-drive car the front wheels roll freely, so their
speed is road speed. Correct and available, but it arrives quantised by the
capture timer and carries tone-ring error, and it says nothing between
samples.

FUSED. A Kalman filter running the accelerometer forward and correcting it
against the undriven wheel. The accelerometer has the bandwidth and drifts;
the wheel is absolute and coarse. Each covers the other's failure, which is
the entire reason to fuse rather than pick.
"""

import numpy as np

import vehicle
import controllers

DT = 1e-3
CONTROL_DT = 1.0 / vehicle.CONTROL_HZ

# --- what the sensors are actually like -----------------------------------
TEETH = 48                 # tone ring teeth per wheel revolution
TIMER_TICK = 1e-6          # s, capture timer resolution
ACCEL_NOISE = 0.05         # m/s^2, one sigma
ACCEL_BIAS = 0.15          # m/s^2, a real bias the filter has to find
WHEEL_NOISE = 0.02         # m/s, one sigma of sensor and tone-ring error

rng = np.random.default_rng(7)


def measured_wheel_speed(omega: float, radius: float) -> float:
    """Road speed as a toothed sensor reports it.

    The first version of this counted whole pulses inside each control window.
    That is not how the sensor works, and it matters: at 48 teeth and 100 Hz
    only about three pulses land per window, so flooring them threw away 13% of
    the speed and the filter spent its whole time fighting a measurement that
    was systematically low.

    A real sensor captures the TIME BETWEEN TOOTH EDGES with a hardware timer.
    Resolution then comes from the timer tick, which is excellent at low speed
    and degrades at high speed — the opposite way round.
    """
    if omega <= 1e-6:
        return 0.0
    period = 2.0 * np.pi / (TEETH * abs(omega))
    ticks = max(1.0, round(period / TIMER_TICK))
    omega_measured = 2.0 * np.pi / (TEETH * ticks * TIMER_TICK)
    return omega_measured * radius + rng.normal(0.0, WHEEL_NOISE)


class SpeedEstimator:
    """Kalman filter on [road speed, accelerometer bias].

    Two states, because a bias that is not estimated is a bias that integrates
    into the speed and never comes out. The wheel measurement is what observes
    it: the filter can only separate bias from speed because it has an
    absolute reference to drift against.
    """

    def __init__(self, v0: float, dt: float = CONTROL_DT):
        self.dt = dt
        self.x = np.array([v0, 0.0])
        self.P = np.diag([0.5, 0.5])
        # Process noise: speed is driven by a noisy accelerometer, bias walks
        # very slowly. Measurement noise covers quantisation plus sensor noise.
        self.Q = np.diag([(ACCEL_NOISE * dt) ** 2, 1e-7])
        self.R = np.array([[0.06 ** 2]])
        self.H = np.array([[1.0, 0.0]])

    def step(self, accel_measured: float, wheel_speed: float) -> float:
        dt = self.dt
        F = np.array([[1.0, -dt], [0.0, 1.0]])
        B = np.array([dt, 0.0])

        self.x = F @ self.x + B * accel_measured
        self.P = F @ self.P @ F.T + self.Q

        y = np.array([wheel_speed]) - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + (K @ y).ravel()
        self.P = (np.eye(2) - K @ self.H) @ self.P
        return float(self.x[0])

    @property
    def bias(self) -> float:
        return float(self.x[1])


def run():
    """One corner exit, logging truth and all three estimates."""
    car = vehicle.Vehicle(mu_peak=1.00)   # the off-design case, where it bites
    target = vehicle.peak_slip(vehicle.Vehicle(mu_peak=1.45))
    ctrl = controllers.SlidingMode(target=target)
    ctrl.reset()

    v0 = vehicle.V_EXIT_KPH / 3.6
    kf = SpeedEstimator(v0)
    log = {k: [] for k in ("t", "v_true", "v_driven", "v_wheel", "v_kf",
                           "k_true", "k_driven", "k_kf", "bias")}

    state = np.array([v0, v0 / car.wheel_radius, 1.0])
    every = int(round(CONTROL_DT / DT))
    u = 1.0
    last_accel = 0.0

    for i in range(int(3.0 / DT)):
        v, omega = state[0], state[1]

        if i % every == 0:
            # The front wheels roll freely on a rear-drive car under power, so
            # their speed is road speed — reported through a toothed sensor.
            wheel = measured_wheel_speed(v / car.wheel_radius,
                                         car.wheel_radius)
            accel = last_accel + ACCEL_BIAS + rng.normal(0.0, ACCEL_NOISE)
            v_kf = kf.step(accel, wheel)
            v_driven = omega * car.wheel_radius   # circular, and wrong

            # The controller drives on the fused estimate, as it would on a car.
            k_est = vehicle.slip_ratio(omega, v_kf, car.wheel_radius)
            u = float(np.clip(ctrl(i * DT, state[:2], k_est, car, CONTROL_DT),
                              0.0, 1.0))

            log["t"].append(i * DT)
            log["v_true"].append(v)
            log["v_driven"].append(v_driven)
            log["v_wheel"].append(wheel)
            log["v_kf"].append(v_kf)
            log["bias"].append(kf.bias)
            log["k_true"].append(vehicle.slip_ratio(omega, v, car.wheel_radius))
            log["k_driven"].append(
                vehicle.slip_ratio(omega, v_driven, car.wheel_radius))
            log["k_kf"].append(k_est)

        d1, _, _ = vehicle.derivatives(state, u, car)
        d2, _, _ = vehicle.derivatives(state + 0.5 * DT * d1, u, car)
        d3, _, _ = vehicle.derivatives(state + 0.5 * DT * d2, u, car)
        d4, _, _ = vehicle.derivatives(state + DT * d3, u, car)
        last_accel = float(d1[0])
        state = state + (DT / 6.0) * (d1 + 2 * d2 + 2 * d3 + d4)
        state[1] = max(state[1], 0.0)
        state[2] = min(max(state[2], 0.0), 1.0)

    return {k: np.asarray(v) for k, v in log.items()}


def main():
    log = run()
    settled = log["t"] > 0.2

    def rms(a, b):
        return float(np.sqrt(np.mean((a[settled] - b[settled]) ** 2)))

    print("Road speed estimate error, RMS over the corner exit (m/s):")
    print(f"  driven wheel (circular)   {rms(log['v_driven'], log['v_true']):>8.3f}")
    print(f"  undriven wheel, raw       {rms(log['v_wheel'], log['v_true']):>8.3f}")
    print(f"  fused (Kalman)            {rms(log['v_kf'], log['v_true']):>8.3f}")

    print("\nSlip ratio error, RMS:")
    print(f"  from driven wheel         {rms(log['k_driven'], log['k_true']):>8.3f}")
    print(f"  from fused estimate       {rms(log['k_kf'], log['k_true']):>8.3f}")

    peak_true = log["k_true"].max()
    peak_seen = log["k_driven"].max()
    print(f"\nPeak slip actually reached:            {peak_true:.3f}")
    print(f"Peak slip the driven wheel reports:    {peak_seen:.3f}")
    print("A controller fed the second number sees almost nothing to correct.")

    print(f"\nAccelerometer bias: {ACCEL_BIAS:.3f} m/s^2 injected, "
          f"{log['bias'][-1]:.3f} estimated.")

    try:
        import plot_estimator
        plot_estimator.draw(log)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
