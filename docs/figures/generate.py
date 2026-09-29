#!/usr/bin/env python3
"""Architecture figures for the Torin Architecture document.

Every box is a component that exists in the current tree; every arrow is a
path that exists in the current source. Nothing here is decorative.

  fig1_subsystems  every subsystem, grouped by the role it plays
  fig2_cycle     the cognitive cycle, with the two gates marked
  fig3_dataflow  what feeds each subsystem and what it emits
  fig4_acting    the acting path, step by step
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "."

NAVY = "#1A233A"
SLATE = "#3E4A63"
MIST = "#E8ECF3"
PAPER = "#FFFFFF"
RULE = "#98A2B3"
ACCENT = "#7A2E2E"
BLUSH = "#FDF6F6"
SAGE = "#EEF3EE"
GREEN = "#2F5D3A"

F = {"family": "DejaVu Sans"}


def box(ax, x, y, w, h, title, sub=None, fc=PAPER, ec=SLATE, tc=NAVY,
        ts=8.0, ss=6.2, lw=1.0, rs=0.012, title_y=0.62, sub_y=0.27):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0.003,rounding_size={rs}",
        linewidth=lw, edgecolor=ec, facecolor=fc, zorder=2))
    if sub:
        ax.text(x + w / 2, y + h * title_y, title, ha="center", va="center",
                fontsize=ts, color=tc, fontweight="bold", zorder=3, **F)
        ax.text(x + w / 2, y + h * sub_y, sub, ha="center", va="center",
                fontsize=ss, color=SLATE, zorder=3, **F)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center",
                fontsize=ts, color=tc, fontweight="bold", zorder=3, **F)


def arr(ax, p, q, color=RULE, lw=1.0, rad=0.0, ms=8, ls="-", z=1):
    ax.add_patch(FancyArrowPatch(
        p, q, arrowstyle="-|>", mutation_scale=ms, linewidth=lw, color=color,
        zorder=z, linestyle=ls, connectionstyle=f"arc3,rad={rad}",
        shrinkA=1, shrinkB=1))


def cap(ax, text, y=0.012, fs=7.0):
    ax.text(0.5, y, text, ha="center", va="center", fontsize=fs, color=SLATE, **F)


# ===================== FIGURE 1 — subsystem map ============================
fig, ax = plt.subplots(figsize=(8.2, 6.4))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

BANDS = [
    ("THE BODY", NAVY, MIST,
     [("Constitution", "the act gate"), ("Bearing", "percept stakes"),
      ("Drift", "5 detectors"), ("Reading ledger", "reads + versions"),
      ("Event spine", "8 types / 12 reactions"), ("Appraisal", "11 dims / 7 pressures"),
      ("Planning", "symbolic search"), ("Conversation", "turns, scoped")]),
    ("COGNITION", SLATE, PAPER,
     [("Reasoning", "11 kinds, Z3"), ("Beliefs", "posteriors"),
      ("Learning", "one door"), ("Memory", "5 types, 2 tiers"),
      ("Domain", "competence"), ("Semantics", "read + ADMIT"),
      ("Perception", "classical CV"), ("Intent", "meant vs happened")]),
    ("ACTING", SLATE, PAPER,
     [("Tools", "356 / 16 cats"), ("Execution", "convergence, effects"),
      ("Safety", "consequence class"), ("Integration", "cross-domain master")]),
    ("ASSURANCE", SLATE, PAPER,
     [("Health", "29 components"), ("Observability", "one failure record"),
      ("Chaos", "fault injection")]),
    ("SUPPORT", RULE, PAPER,
     [("Database", "PostgreSQL 16.14"), ("System", "environment state"),
      ("Intelligence", "predictive"), ("Simulation", "numerical"),
      ("Utils", "env, notify, ports")]),
]

top, bot = 0.935, 0.075
n_bands = len(BANDS)
band_h = (top - bot) / n_bands
for bi, (label, ec, fc, items) in enumerate(BANDS):
    y0 = top - (bi + 1) * band_h
    ax.add_patch(FancyBboxPatch((0.135, y0 + band_h * 0.09), 0.85, band_h * 0.80,
        boxstyle="round,pad=0.004,rounding_size=0.012",
        linewidth=1.3, edgecolor=ec, facecolor=fc if bi == 0 else "#FCFCFD", zorder=0))
    ax.text(0.125, y0 + band_h / 2, label, ha="right", va="center",
            fontsize=7.6, color=ec, fontweight="bold", **F)
    k = len(items)
    iw = (0.83 - (k + 1) * 0.008) / k
    for i, (t, s) in enumerate(items):
        x = 0.143 + 0.008 + i * (iw + 0.008)
        box(ax, x, y0 + band_h * 0.20, iw, band_h * 0.56, t, s,
            fc=PAPER, ec=SLATE, ts=6.5, ss=5.2, title_y=0.66, sub_y=0.26)

ax.text(0.5, 0.042, "governance is the Constitution, and drift the Drift faculty — both held by the body, not separate subsystems",
        ha="center", va="center", fontsize=6.2, color=SLATE, style="italic", **F)
cap(ax, "Figure 1 — Subsystem map. The body holds every authority; each subsystem owns one concept.",
    y=0.014, fs=6.8)
plt.tight_layout(pad=0.15)
plt.savefig(f"{OUT}/fig1_subsystems.png", dpi=260, facecolor="white",
            bbox_inches="tight", pad_inches=0.06)
plt.close()


# ===================== FIGURE 2 — the cognitive cycle ======================
fig, ax = plt.subplots(figsize=(7.6, 4.3))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

box(ax, 0.055, 0.735, 0.20, 0.135, "THE WORLD", "images · video · sensors\nfiles · people",
    fc="#F4F4F2", ec=SLATE, ts=8.0, ss=6.0)
box(ax, 0.055, 0.470, 0.20, 0.135, "Perception · Tools", "classical CV\ngoverned tool output",
    ts=7.4, ss=6.0)

# admission gate
box(ax, 0.315, 0.470, 0.245, 0.400, "ADMISSION GATE",
    "cognitive_ingress\n\nshape · quality ≥ 0.5\nprovenance · actor scope\n\nNOT truth",
    fc=BLUSH, ec=ACCENT, lw=1.6, ts=8.6, ss=6.4, title_y=0.86, sub_y=0.40)

box(ax, 0.625, 0.735, 0.32, 0.135, "Knowledge", "concepts · aliases · evidence\nmemory episode",
    ts=7.6, ss=6.0)
box(ax, 0.625, 0.545, 0.32, 0.135, "Beliefs", "posterior, not a flag\nrevised · decays · persists",
    fc=BLUSH, ec=ACCENT, lw=1.3, ts=7.6, ss=6.0)
box(ax, 0.625, 0.355, 0.32, 0.135, "Reasoning · Planning", "11 kinds · formal solver\nproved route or none",
    ts=7.6, ss=6.0)
box(ax, 0.625, 0.165, 0.32, 0.135, "Intent", "what it meant,\nrecorded before acting",
    ts=7.6, ss=6.0)

# action gate
box(ax, 0.315, 0.165, 0.245, 0.240, "ACTION GATE",
    "the constitution\n\n5 laws · 4 verdicts\nfails closed\n\nonly ALLOW proceeds",
    fc=BLUSH, ec=ACCENT, lw=1.6, ts=8.6, ss=6.4, title_y=0.86, sub_y=0.36)

box(ax, 0.055, 0.165, 0.20, 0.135, "Act on the world", "then RE-OBSERVE\nthe world decides",
    fc="#F4F4F2", ec=SLATE, ts=7.4, ss=6.0)

arr(ax, (0.155, 0.735), (0.155, 0.610), lw=1.1)
arr(ax, (0.255, 0.537), (0.315, 0.615), lw=1.1)
arr(ax, (0.560, 0.760), (0.625, 0.795), lw=1.1)
arr(ax, (0.785, 0.735), (0.785, 0.685), lw=1.1)
arr(ax, (0.785, 0.545), (0.785, 0.495), lw=1.1)
arr(ax, (0.785, 0.355), (0.785, 0.305), lw=1.1)
arr(ax, (0.625, 0.232), (0.560, 0.268), lw=1.1)
arr(ax, (0.315, 0.232), (0.255, 0.232), lw=1.3, color=ACCENT)
arr(ax, (0.100, 0.300), (0.100, 0.455), lw=1.1, ls="--")
ax.text(0.118, 0.378, "re-observed", ha="left", va="center", fontsize=6.0,
        color=SLATE, style="italic", **F)

cap(ax, "Figure 2 — The cognitive cycle. Nothing enters knowledge except through the admission "
        "gate; nothing reaches the world except through the action gate.", y=0.045, fs=6.8)
plt.tight_layout(pad=0.15)
plt.savefig(f"{OUT}/fig2_cycle.png", dpi=260, facecolor="white",
            bbox_inches="tight", pad_inches=0.06)
plt.close()


# ===================== FIGURE 3 — feeds / emits ============================
rows = [
    ("Semantics / Ingress", "sentences · percepts · tool output",
     "admitted propositions → concepts,\naliases, evidence root, episode"),
    ("Beliefs", "evidence from every producer",
     "posteriors → completion, answer/abstain,\nexploration, memory stamping"),
    ("Reasoning", "queries · beliefs · concepts · rules",
     "conclusions · hypotheses · intent\nepistemic affect signal"),
    ("Learning", "executed actions · teaching\nperception · research",
     "operators + rule status; fan-out to beliefs,\ndomain, lexicon, memory, reasoning"),
    ("Memory", "episodes · percepts\nbelief + appraisal state",
     "recall for planning and question answering,\nschemas by abstraction"),
    ("Domain", "outcomes · concepts · transfers",
     "competence · controllability\noperating reliability (the KNOW→DO bar)"),
    ("Perception", "images · video · sensors · files",
     "percepts + recognitions, submitted as\nevidence with confidence — never as truth"),
    ("Planning", "observed world · operators · reliability\ntool history · abstraction · memory",
     "proved route, UNREACHABLE,\nor INDETERMINATE — never a guess"),
    ("Intent", "reasoning engagement · proved routes",
     "shape (substrate-wide) + content (actor-scoped),\nreconciled verdict after acting"),
    ("Constitution", "the act · declared capability · intent\nreading ledger · actor",
     "allow · redirect · replan · block,\nnaming the law and the reason"),
    ("Appraisal", "affect signals · outcomes · bearing",
     "disposition: 11 dimensions →\n7 behavioural pressures"),
    ("Drift", "declared baselines · live observations",
     "severity per signal → caution,\nreplan, escalation"),
]
fig, ax = plt.subplots(figsize=(8.0, 8.4))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

top, bot = 0.955, 0.055
rh = (top - bot) / len(rows)
xf, xs, xe = 0.015, 0.345, 0.575
wf, ws, we = 0.315, 0.215, 0.410

ax.text(xf + wf / 2, 0.978, "WHAT FEEDS IT", ha="center", va="center",
        fontsize=7.4, color=SLATE, fontweight="bold", **F)
ax.text(xs + ws / 2, 0.978, "SUBSYSTEM", ha="center", va="center",
        fontsize=7.4, color=NAVY, fontweight="bold", **F)
ax.text(xe + we / 2, 0.978, "WHAT IT EMITS", ha="center", va="center",
        fontsize=7.4, color=SLATE, fontweight="bold", **F)

for i, (name, feeds, emits) in enumerate(rows):
    y = top - (i + 1) * rh + rh * 0.13
    h = rh * 0.74
    gate = name in ("Semantics / Ingress", "Constitution")
    ax.text(xf + wf, y + h / 2, feeds, ha="right", va="center",
            fontsize=6.3, color=SLATE, **F)
    box(ax, xs, y, ws, h, name,
        fc=BLUSH if gate else PAPER, ec=ACCENT if gate else SLATE,
        lw=1.4 if gate else 1.0, ts=7.4)
    ax.text(xe, y + h / 2, emits, ha="left", va="center",
            fontsize=6.3, color=SLATE, **F)
    arr(ax, (xf + wf + 0.008, y + h / 2), (xs - 0.004, y + h / 2), lw=0.9, ms=7)
    arr(ax, (xs + ws + 0.004, y + h / 2), (xe - 0.008, y + h / 2), lw=0.9, ms=7)

cap(ax, "Figure 3 — What feeds each subsystem, and what it emits. The two shaded rows are the gates: "
        "nothing enters knowledge or reaches the world around them.", y=0.020, fs=6.6)
plt.tight_layout(pad=0.15)
plt.savefig(f"{OUT}/fig3_dataflow.png", dpi=260, facecolor="white",
            bbox_inches="tight", pad_inches=0.06)
plt.close()


# ===================== FIGURE 4 — the acting path ==========================
fig, ax = plt.subplots(figsize=(8.6, 2.75))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
steps = [
    ("Act composed", "declares its own\nsafety + capability"),
    ("Intent + actor", "from async context,\nnot from arguments"),
    ("Constitution\njudges", "5 laws, strongest\nverdict first"),
    ("Verdict", "allow · redirect\nreplan · block"),
    ("Execute", "only ALLOW\nproceeds"),
    ("Re-observe", "no trace left;\nthe world decides"),
]
n = len(steps); gap = 0.028
bw = (1 - (n + 1) * gap) / n
for i, (t, s) in enumerate(steps):
    x = gap + i * (bw + gap)
    g = i == 2
    box(ax, x, 0.36, bw, 0.42, t, s, fc=BLUSH if g else PAPER,
        ec=ACCENT if g else SLATE, lw=1.5 if g else 1.0, ts=7.6, ss=6.0)
    if i:
        arr(ax, (x - gap, 0.57), (x - 0.002, 0.57), color=SLATE, lw=1.1, z=3)
ax.text(0.5, 0.20, "fails closed at every step — a judgement that cannot be reached, "
                   "breaks mid-way, or an argument that cannot be screened all refuse the act",
        ha="center", va="center", fontsize=6.8, color=SLATE, style="italic", **F)
cap(ax, "Figure 4 — The acting path", y=0.05)
plt.tight_layout(pad=0.15)
plt.savefig(f"{OUT}/fig4_acting.png", dpi=260, facecolor="white",
            bbox_inches="tight", pad_inches=0.06)
plt.close()

print("4 figures written")
