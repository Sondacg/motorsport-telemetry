#!/usr/bin/env python3
"""Draw the estimator: what each source of road speed thinks is happening."""

import os

BG = "#080B0D"
PANEL = "#10161A"
TEXT = "#E9EFF2"
MUTED = "#5E727C"
EDGE = "#1E2A31"
RED = "#E2452F"
AMBER = "#F0A73A"
GREEN = "#39D07A"
BLUE = "#5AB4FF"

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "docs", "estimator.png")


def _style(ax):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=MUTED, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(EDGE)
    ax.grid(color=EDGE, linewidth=0.7)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.title.set_color(TEXT)


def draw(log, out=OUT):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), facecolor=BG)
    for ax in axes:
        _style(ax)

    t = log["t"]

    # 1 — three answers to "how fast is the car going"
    ax = axes[0]
    ax.plot(t, log["v_true"] * 3.6, color=TEXT, linewidth=3.4, alpha=0.85,
            label="truth")
    ax.plot(t, log["v_driven"] * 3.6, color=RED, linewidth=1.5,
            label="driven wheel")
    ax.plot(t, log["v_wheel"] * 3.6, color=AMBER, linewidth=0.9, alpha=0.8,
            label="undriven wheel")
    ax.plot(t, log["v_kf"] * 3.6, color=GREEN, linewidth=1.5,
            linestyle="--", label="fused")
    ax.set_title("Road speed", fontsize=11)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("km/h")
    leg = ax.legend(facecolor=PANEL, edgecolor=EDGE, fontsize=8.5)
    for txt in leg.get_texts():
        txt.set_color(TEXT)

    # 2 — and what that does to the number the controller acts on
    ax = axes[1]
    ax.plot(t, log["k_true"], color=TEXT, linewidth=3.4, alpha=0.85,
            label="true slip")
    ax.plot(t, log["k_driven"], color=RED, linewidth=1.6,
            label="as the driven wheel sees it")
    ax.plot(t, log["k_kf"], color=GREEN, linewidth=1.4, linestyle="--",
            label="from the estimate")
    ax.set_title("Slip ratio", fontsize=11)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("slip ratio κ")
    ax.annotate("the wheel it is controlling\nreports nothing wrong",
                xy=(0.35, log["k_driven"].max() + 0.02), xytext=(0.9, 0.42),
                color=RED, fontsize=9.5, ha="center",
                arrowprops=dict(color=RED, arrowstyle="->", linewidth=1))
    leg = ax.legend(facecolor=PANEL, edgecolor=EDGE, fontsize=8.5)
    for txt in leg.get_texts():
        txt.set_color(TEXT)

    # 3 — the state that exists only so the other one can be trusted
    ax = axes[2]
    ax.plot(t, log["bias"], color=BLUE, linewidth=1.8, label="estimated")
    ax.axhline(0.15, color=MUTED, linestyle="--", linewidth=1.2,
               label="injected")
    ax.set_title("Accelerometer bias", fontsize=11)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("m/s²")
    leg = ax.legend(facecolor=PANEL, edgecolor=EDGE, fontsize=8.5)
    for txt in leg.get_texts():
        txt.set_color(TEXT)

    fig.tight_layout()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110, facecolor=BG)
    print(f"wrote {os.path.normpath(out)}")
