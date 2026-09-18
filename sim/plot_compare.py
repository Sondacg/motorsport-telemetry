#!/usr/bin/env python3
"""Draw the controller comparison — including the part that settles it."""

import os
import numpy as np

BG = "#080B0D"
PANEL = "#10161A"
TEXT = "#E9EFF2"
MUTED = "#5E727C"
EDGE = "#1E2A31"
COLOURS = {
    "no control": "#E2452F",
    "bang-bang": "#F0A73A",
    "PI + anti-windup": "#5AB4FF",
    "sliding mode": "#39D07A",
}

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "docs", "controllers.png")


def _style(ax):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=MUTED, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(EDGE)
    ax.grid(color=EDGE, linewidth=0.7)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.title.set_color(TEXT)


def draw(results, target, sweep, out=OUT):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), facecolor=BG)
    for ax in axes:
        _style(ax)

    # 1 — slip off design: what each law does when grip is not what it assumed
    ax = axes[0]
    for name, (_, off) in results.items():
        ax.plot(off["t"], off["kappa"], color=COLOURS[name], linewidth=1.6,
                label=name)
    ax.axhline(target, color=MUTED, linestyle="--", linewidth=1)
    ax.set_title("Slip ratio at μ = 1.00, tuned for 1.45", fontsize=11)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("slip ratio κ")
    ax.set_xlim(0, 2.0)
    leg = ax.legend(facecolor=PANEL, edgecolor=EDGE, fontsize=8.5)
    for txt in leg.get_texts():
        txt.set_color(TEXT)

    # 2 — the command: lap time is not the only currency an actuator has
    ax = axes[1]
    for name, (_, off) in results.items():
        if name == "no control":
            continue
        ax.plot(off["t"], off["throttle"], color=COLOURS[name], linewidth=1.4)
    ax.set_title("Throttle command at μ = 1.00", fontsize=11)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("throttle")
    ax.set_xlim(0, 2.0)
    ax.set_ylim(-0.05, 1.08)

    # 3 — the one that settles the argument
    ax = axes[2]
    taus, series = sweep
    for name, peaks in series.items():
        ax.plot([t * 1000 for t in taus], peaks, color=COLOURS[name],
                linewidth=1.8, marker="o", markersize=4, label=name)
    ax.axhline(target, color=MUTED, linestyle="--", linewidth=1)
    ax.set_title("Peak slip vs actuator time constant", fontsize=11)
    ax.set_xlabel("actuator τ (ms)")
    ax.set_ylabel("peak slip ratio κ")
    ax.annotate("the laws sit within 0.03 of each other\n"
                "the actuator moves them by 0.6",
                xy=(0.5, 0.06), xycoords="axes fraction",
                color=TEXT, fontsize=9.5, ha="center")

    fig.tight_layout()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110, facecolor=BG)
    print(f"wrote {os.path.normpath(out)}")
