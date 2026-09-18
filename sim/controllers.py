#!/usr/bin/env python3
"""Three traction control laws, to be compared against the plant.

Each one answers the same question — how much throttle, given the slip the
tyre is showing — and each is wrong in a different way. That is the point of
having three: a single candidate cannot be defended, only asserted.

The control signal is throttle in [0, 1]. Full throttle is the default and the
controller only ever subtracts from it: the driver asked for everything, and
the job is to hand over as much of it as the tyre will take.
"""

from dataclasses import dataclass, field
import math


def saturate(x: float, width: float) -> float:
    """sign(x) with the discontinuity smeared over a boundary layer.

    Sliding mode with a true sign() chatters at whatever rate it is sampled;
    on a real actuator that is heat and wear. The boundary layer trades a
    little steady-state accuracy for a control signal that can be executed.
    """
    return max(-1.0, min(1.0, x / width))


@dataclass
class BangBang:
    """Cut the throttle above the slip target, restore it below.

    The naive answer, and worth including precisely because it is what gets
    written when nobody asks for a design. It has no tuning to get wrong, which
    is its only virtue.
    """

    target: float = 0.13
    name: str = "bang-bang"

    def reset(self):
        pass

    def __call__(self, t, state, kappa, car, dt):
        return 0.0 if kappa > self.target else 1.0


@dataclass
class PI:
    """Proportional-integral regulation of slip error, with anti-windup.

    The obvious engineering answer. The integral term is what lets it hold the
    target exactly rather than settling near it, and the anti-windup is what
    stops that same term from filling up while the throttle is already shut and
    then refusing to let go when grip returns.
    """

    target: float = 0.13
    kp: float = 14.0
    ki: float = 45.0
    name: str = "PI + anti-windup"
    _integral: float = field(default=0.0, init=False)

    def reset(self):
        self._integral = 0.0

    def __call__(self, t, state, kappa, car, dt):
        error = self.target - kappa
        raw = 1.0 + self.kp * error + self.ki * self._integral
        u = max(0.0, min(1.0, raw))
        # Conditional integration: stop accumulating when the command is
        # already against the stop and the error would push it further.
        if u == raw or (u == 0.0 and error > 0) or (u == 1.0 and error < 0):
            self._integral += error * dt
        return u


@dataclass
class SlidingMode:
    """Equivalent control from the model, plus a robust term that fixes it.

    s = kappa - target is the surface. The equivalent-control part asks the
    model what throttle would hold the wheel exactly where it is; the switching
    part covers everything the model got wrong. That split is the whole idea:
    the model does the easy work, and the robust term absorbs the difference
    between the tyre that was modelled and the tyre that is actually on the car.
    """

    target: float = 0.13
    gain: float = 0.85
    boundary: float = 0.03
    mu_assumed: float = 1.45
    name: str = "sliding mode"

    def reset(self):
        pass

    def equivalent_throttle(self, state, kappa, car) -> float:
        """Throttle that would make the wheel neither spin up nor slow down.

        Torque balance at the wheel: engine torque equals tyre force times
        radius. Uses the ASSUMED friction, not the real one — that error is
        what the switching term is there to cover.
        """
        v, omega = state
        assumed = car.mu_peak
        car.mu_peak = self.mu_assumed
        try:
            load = car.rear_normal_load(0.0)
            needed = car.tyre_force(kappa, load) * car.wheel_radius
        finally:
            car.mu_peak = assumed

        available = car.engine_torque(omega, 1.0)
        if available <= 1e-6:
            return 0.0
        return max(0.0, min(1.0, needed / available))

    def __call__(self, t, state, kappa, car, dt):
        s = kappa - self.target
        u_eq = self.equivalent_throttle(state, kappa, car)
        return max(0.0, min(1.0, u_eq - self.gain * saturate(s, self.boundary)))


def open_loop(t, state, kappa, car, dt):
    return 1.0


open_loop.name = "no control"
open_loop.reset = lambda: None


ALL = [open_loop, BangBang(), PI(), SlidingMode()]
