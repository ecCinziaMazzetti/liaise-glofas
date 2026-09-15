#!/usr/bin/env python3
"""docs/figures/performance.png: wall-clock per simulated year on the LIAISE grid (17,520 half-hourly
steps). Numbers: Fortran 8.8 ms/step (control run, 4 OpenMP threads); eclandpy 24 ms/step on one
EPYC-7742 core and 32 ms/step on one A100 (37 with the recorders; the 37-year GPU run's measured
10.8 min/year); the archived CPU run's 30.5 min/year was pre-merge ecland-porting (104 ms/step)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rows = [  # label, minutes per year, colour, hatch, note
    ("Fortran ecLand\n4 OpenMP threads", 2.56, "#8a8a8a", "", "2.6 min (measured)"),
    ("eclandpy CPU, 1 core\ncurrent code, 24 ms/step", 24e-3 * 17520 / 60, "#bcb8ae", "//", "7.0 min (projected)"),
    ("eclandpy CPU, 1 core\nas run, pre-merge code", 30.5, "#bcb8ae", "", "30.5 min (measured)"),
    ("eclandpy GPU\n1× A100, gt:gpu", 10.8, "#2a6fb0", "", "10.8 min (measured)"),
]
fig, ax = plt.subplots(figsize=(11.2, 5.4), dpi=100)
y = range(len(rows))[::-1]
for yi, (lab, v, c, h, note) in zip(y, rows):
    ax.barh(yi, v, color=c, hatch=h, edgecolor="white" if not h else "#7a766d", linewidth=0.8)
    ax.text(v + 0.5, yi, note, va="center", fontsize=12)
ax.set_yticks(list(y)); ax.set_yticklabels([r[0] for r in rows], fontsize=12)
ax.set_xlabel("wall-clock minutes per simulated year (368 columns, 17,520 steps)", fontsize=12)
ax.set_title("Time per year, LIAISE 16×23 grid", loc="left", fontsize=13)
ax.set_xlim(0, 36)
for s in ("top", "right"): ax.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig("/perm/pad/liaise-ecland/docs/figures/performance.png")
print("wrote docs/figures/performance.png")
