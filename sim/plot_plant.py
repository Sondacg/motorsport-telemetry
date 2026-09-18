#!/usr/bin/env python3
"""Draw the plant: the tyre curve, and what ignoring it costs.

Imported by vehicle.py when matplotlib is available, or run directly.
"""

import os
import numpy as np

BG = "#080B0D"
PANEL = "#10161A"
TEXT = "#E9EFF2"
MUTED = "#5E727C"
GREEN = "#39D07A"
AMBER = "#F0A73A"
RED = "#E2452F"
BLUE = "#5AB4FF"

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "docs", "plant.png")


def draw(car, k_peak, flat_out, ideal, out=OUT):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), facecolor=BG)
    for ax in axes:
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=MUTED, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#1E2A31")
        ax.grid(color="#1E2A31", linewidth=0.7)
        ax.xaxis.label.set_color(MUTED)
        ax.yaxis.label.set_color(MUTED)
        ax.title.set_color(TEXT)

    # 1 — the tyre curve, which is the whole reason the problem exists
    ax = axes[0]
    k = np.linspace(0, 0.9, 400)
    f = np.array([car.tyre_force(x, 1.0) for x in k]) / car.mu_peak
    ax.plot(k, f, color=TEXT, linewidth=2)
    ax.axvline(k_peak, color=GREEN, linestyle="--", linewidth=1.2)
    ax.fill_between(k, 0, f, where=(k > k_peak), color=RED, alpha=0.07)
    ax.annotate(f"peak  κ = {k_peak:.2f}", xy=(k_peak, 1.0),
                xytext=(0.34, 1.06), color=GREEN, fontsize=9.5,
                arrowprops=dict(color=GREEN, arrowstyle="->", linewidth=1))
    ax.text(0.56, 0.40, "past the peak,\nmore slip = less force",
            color=RED, fontsize=9.5, ha="center")
    ax.set_title("Tyre: longitudinal force vs slip ratio", fontsize=11)
    ax.set_xlabel("slip ratio κ")
    ax.set_ylabel("force / peak force")
    ax.set_ylim(0, 1.12)

    # 2 — slip over the corner exit
    ax = axes[1]
    ax.plot(flat_out["t"], flat_out["kappa"], color=RED, linewidth=1.8,
            label="full throttle")
    ax.plot(ideal["t"], ideal["kappa"], color=GREEN, linewidth=1.8,
            label="slip held at peak")
    ax.axhline(k_peak, color=MUTED, linestyle="--", linewidth=1)
    ax.set_title("Slip ratio out of the corner", fontsize=11)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("slip ratio κ")
    leg = ax.legend(facecolor=PANEL, edgecolor="#1E2A31", fontsize=9)
    for txt in leg.get_texts():
        txt.set_color(TEXT)

    # 3 — and what it costs in the only currency that matters
    ax = axes[2]
    ax.plot(flat_out["t"], flat_out["v"] * 3.6, color=RED, linewidth=1.8)
    ax.plot(ideal["t"], ideal["v"] * 3.6, color=GREEN, linewidth=1.8)
    ax.axhline(100, color=MUTED, linestyle="--", linewidth=1)
    ax.set_title("Road speed", fontsize=11)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("km/h")

    fig.tight_layout()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110, facecolor=BG)
    print(f"wrote {os.path.normpath(out)}")


if __name__ == "__main__":
    import vehicle
    car = vehicle.Vehicle()
    kp = vehicle.peak_slip(car)
    v0 = vehicle.V_EXIT_KPH / 3.6
    draw(car, kp,
         vehicle.simulate(car, lambda t, s, k: 1.0, v0=v0),
         vehicle.simulate(car, lambda t, s, k: 1.0 if k < kp else 0.0, v0=v0))
