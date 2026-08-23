"""OpsPilot design system: tokens and the global stylesheet (Phase 11).

Dark-first premium SaaS aesthetic:

* deep charcoal-navy surfaces (never pure black) with layered ambient
  glows for depth,
* one electric blue/indigo accent family plus restrained semantic
  colors (info cyan, success green, warning amber, danger red, AI
  violet),
* a strict typographic hierarchy (eyebrow labels, strong titles,
  tabular numerals),
* motion limited to 150-400 ms micro-interactions, disabled entirely
  under ``prefers-reduced-motion``.

The stylesheet is injected once per rerun via ``apply_theme``; it themes
both OpsPilot markup and the native Streamlit/baseweb widgets so the
whole application reads as one coherent product without adding any
dependency or touching files outside the presentation layer.
"""

from __future__ import annotations

import streamlit as st

# --- palette ---------------------------------------------------------------------------------
BG = "#0B0E14"
BG_SOFT = "#0F1420"
SURFACE = "#121826"
SURFACE_2 = "#171E30"
LINE = "rgba(148,163,184,.14)"
LINE_STRONG = "rgba(148,163,184,.26)"
TEXT = "#EDF2FA"
TEXT_2 = "#9AA7BD"
# Muted tier stays >= ~4.9:1 on --ops-surface (WCAG AA for small text).
TEXT_3 = "#7C8AA5"

ACCENT = "#5B8CFF"
ACCENT_2 = "#7C6CFF"
INFO = "#38BDF8"
SUCCESS = "#34D399"
WARNING = "#FBBF24"
DANGER = "#F87171"
AI = "#A78BFA"

SEVERITY_COLORS: dict[str, str] = {
    "CRITICAL": DANGER,
    "HIGH": "#FB923C",
    "MEDIUM": WARNING,
    "LOW": INFO,
}

_FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", '
    '"Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif'
)
_MONO_STACK = (
    '"JetBrains Mono", "Cascadia Code", Consolas, "SF Mono", Menlo, monospace'
)


def severity_color(severity: object) -> str:
    """Map a severity/priority label to its semantic color."""
    return SEVERITY_COLORS.get(str(severity).upper(), TEXT_2)


_CSS = """
:root {
  --ops-bg: #0B0E14;
  --ops-bg-soft: #0F1420;
  --ops-surface: #121826;
  --ops-surface-2: #171E30;
  --ops-line: rgba(148,163,184,.14);
  --ops-line-strong: rgba(148,163,184,.26);
  --ops-text: #EDF2FA;
  --ops-text-2: #9AA7BD;
  --ops-text-3: #7C8AA5;
  --ops-accent: #5B8CFF;
  --ops-accent-2: #7C6CFF;
  --ops-accent-soft: rgba(91,140,255,.14);
  --ops-info: #38BDF8;
  --ops-success: #34D399;
  --ops-warning: #FBBF24;
  --ops-danger: #F87171;
  --ops-ai: #A78BFA;
  --ops-radius-lg: 16px;
  --ops-radius: 12px;
  --ops-radius-sm: 9px;
  --ops-shadow: 0 12px 32px rgba(2,6,17,.45);
  --ops-glow: 0 6px 22px rgba(91,140,255,.28);
}

/* ---- base surface ----------------------------------------------------------------------- */
.stApp {
  background:
    radial-gradient(1100px 520px at 85% -10%, rgba(124,108,255,.10), transparent 60%),
    radial-gradient(900px 480px at -15% 0%, rgba(56,189,248,.07), transparent 55%),
    radial-gradient(1200px 700px at 50% 115%, rgba(91,140,255,.06), transparent 60%),
    var(--ops-bg);
  color: var(--ops-text);
}
.stApp::before {
  content: "";
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  opacity: .035;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
/* NAVIGATION SAFETY: the Streamlit header hosts the ONLY control that
   re-expands a collapsed sidebar (stExpandSidebarButton). Never hide the
   header or that button — hiding them made a collapsed sidebar
   permanently inaccessible (Phase 11B navigation regression). Keep the
   header transparent so the premium surface is preserved while the
   toggle stays visible and clickable at every viewport width. */
#MainMenu { visibility: hidden; }
header[data-testid="stHeader"] {
  background: transparent;
}
[data-testid="stExpandSidebarButton"] {
  color: var(--ops-text-2) !important;
  background: var(--ops-surface);
  border: 1px solid var(--ops-line-strong);
  border-radius: 8px;
}
[data-testid="stExpandSidebarButton"]:hover {
  color: var(--ops-text) !important;
  border-color: var(--ops-accent);
}
.block-container { padding-top: 1.4rem; max-width: 1280px; }
.stApp > div { position: relative; z-index: 1; }

h1, h2, h3, h4 { color: var(--ops-text); letter-spacing: -.01em; font-weight: 650; }
a { color: var(--ops-accent); }
strong { color: var(--ops-text); }
hr { border-color: var(--ops-line); opacity: .7; }
::selection { background: rgba(91,140,255,.35); }
*::-webkit-scrollbar { width: 9px; height: 9px; }
*::-webkit-scrollbar-thumb { background: rgba(148,163,184,.22); border-radius: 99px; }
*::-webkit-scrollbar-thumb:hover { background: rgba(148,163,184,.38); }
*::-webkit-scrollbar-track { background: transparent; }

:focus-visible {
  outline: 2px solid var(--ops-accent) !important;
  outline-offset: 2px; border-radius: 6px;
}

/* ---- sidebar ---------------------------------------------------------------------------- */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, rgba(23,30,48,.65), rgba(11,14,20,.92)),
              var(--ops-bg-soft);
  border-right: 1px solid var(--ops-line);
}
[data-testid="stSidebar"] .block-container { padding-top: 1.6rem; }
[data-testid="stSidebar"] * { color: var(--ops-text-2); }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] .ops-brand-name { color: var(--ops-text) !important; }
[data-testid="stSidebar"] hr { margin: .35rem 0; }

/* sidebar page navigation (st.navigation items) */
[data-testid="stSidebarContent"] > div:first-child { margin-bottom: .4rem; }
[data-testid="stSidebar"] nav a, [data-testid="stSidebar"] [role="menuitem"],
[data-testid="stSidebar"] label[data-testid^="stPageLink"] {
  border-radius: var(--ops-radius-sm);
  transition: background .16s ease, color .16s ease;
}
[data-testid="stSidebar"] nav a:hover, [data-testid="stSidebar"] [role="menuitem"]:hover {
  background: var(--ops-accent-soft);
  color: var(--ops-text) !important;
}

/* ---- buttons ---------------------------------------------------------------------------- */
.stButton button, .stDownloadButton button,
[data-testid^="baseButton-"] {
  border-radius: var(--ops-radius-sm);
  border: 1px solid var(--ops-line-strong);
  background: var(--ops-surface);
  color: var(--ops-text);
  font-weight: 550;
  transition: transform .18s ease, box-shadow .18s ease,
              border-color .18s ease, background .18s ease, filter .18s ease;
}
.stButton button:hover, .stDownloadButton button:hover {
  transform: translateY(-1px);
  border-color: var(--ops-accent);
  box-shadow: 0 4px 16px rgba(91,140,255,.18);
}
.stButton button[kind="primary"], .stDownloadButton button[kind="primary"],
[data-testid="baseButton-primary"] {
  background: linear-gradient(135deg, #4F7CFF, #7C6CFF);
  border: none; color: #fff;
  box-shadow: var(--ops-glow);
}
.stButton button[kind="primary"]:hover {
  filter: brightness(1.08);
  box-shadow: 0 8px 26px rgba(91,124,255,.42);
}
.stButton button:disabled, [data-testid="baseButton-primary"]:disabled {
  opacity: .45; filter: grayscale(.4); transform: none; box-shadow: none;
}
[data-testid="stFormSubmitButton"] button { width: 100%; }

/* ---- inputs ------------------------------------------------------------------------------ */
.stTextInput input, .stTextArea textarea, .stNumberInput input,
div[data-baseweb="select"] > div {
  background: var(--ops-surface) !important;
  border: 1px solid var(--ops-line-strong) !important;
  border-radius: var(--ops-radius-sm) !important;
  color: var(--ops-text) !important;
}
.stTextInput input:focus, .stTextArea textarea:focus,
div[data-baseweb="select"] > div:focus-within {
  border-color: var(--ops-accent) !important;
  box-shadow: 0 0 0 3px rgba(91,140,255,.18) !important;
}
[data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"] {
  background: var(--ops-surface-2) !important;
  border: 1px solid var(--ops-line-strong) !important;
  border-radius: var(--ops-radius) !important;
  box-shadow: var(--ops-shadow) !important;
}
[role="listbox"] li, [role="option"] { color: var(--ops-text) !important; }
[role="option"]:hover { background: var(--ops-accent-soft) !important; }

/* segmented radios become pill toggles */
[data-testid="stRadio"] [role="radiogroup"] { gap: .4rem; }
[data-testid="stRadio"] label {
  background: var(--ops-surface);
  border: 1px solid var(--ops-line-strong);
  border-radius: 999px; padding: .34rem .95rem .34rem .55rem;
  transition: all .18s ease; margin-right: .15rem;
}
[data-testid="stRadio"] label:hover { border-color: var(--ops-accent); }
[data-testid="stRadio"] label[data-checked="true"],
[data-testid="stRadio"] label:has(input:checked) {
  background: var(--ops-accent-soft);
  border-color: var(--ops-accent);
  box-shadow: inset 0 0 0 1px rgba(91,140,255,.35);
}

/* multiselect chips */
[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
  background: var(--ops-accent-soft); border-color: transparent;
  border-radius: 999px; color: var(--ops-text);
}

/* ---- metrics ---------------------------------------------------------------------------- */
[data-testid="stMetric"] {
  background: transparent; padding: .1rem 0;
}
[data-testid="stMetricValue"] {
  color: var(--ops-text); font-variant-numeric: tabular-nums;
  font-weight: 680; letter-spacing: -.01em;
}
[data-testid="stMetricLabel"] p { color: var(--ops-text-2); font-size: .82rem; }

/* ---- expander / tabs / dataframe --------------------------------------------------------- */
[data-testid="stExpander"] details {
  background: color-mix(in srgb, var(--ops-surface) 72%, transparent);
  border: 1px solid var(--ops-line);
  border-radius: var(--ops-radius);
  overflow: hidden;
}
[data-testid="stExpander"] summary { padding: .55rem .5rem; }
[data-testid="stExpander"] summary:hover { color: var(--ops-accent); }
[data-baseweb="tab-list"] { gap: .25rem; border-bottom: 1px solid var(--ops-line); }
[data-baseweb="tab"] { color: var(--ops-text-3); border-radius: 8px 8px 0 0; padding: 6px 12px; }
[data-baseweb="tab"]:hover { color: var(--ops-text); background: var(--ops-accent-soft); }
[data-baseweb="tab"][aria-selected="true"] {
  color: var(--ops-accent); border-bottom: 2px solid var(--ops-accent);
  background: transparent;
}
[data-testid="stDataFrame"] {
  border: 1px solid var(--ops-line); border-radius: var(--ops-radius);
  overflow: hidden;
}
[data-testid="stPageLink-NavLink"] {
  color: var(--ops-accent); text-decoration: none; font-weight: 550;
}

/* native bordered containers become surface panels */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: linear-gradient(180deg, rgba(23,30,48,.5), rgba(18,24,38,.8));
  border: 1px solid var(--ops-line) !important;
  border-radius: var(--ops-radius-lg) !important;
  box-shadow: var(--ops-shadow);
}

/* ---- alerts ------------------------------------------------------------------------------ */
[data-testid="stAlert"] {
  border-radius: var(--ops-radius);
  border: 1px solid var(--ops-line-strong);
  background: color-mix(in srgb, var(--ops-surface) 82%, transparent);
}
[data-testid="stAlert"] p, [data-testid="stAlert"] li { color: var(--ops-text-2); }
[data-testid="stAlert"] svg { fill: currentColor; }

/* ---- toast / spinner ---------------------------------------------------------------------- */
[data-testid="stToast"] {
  background: var(--ops-surface-2); color: var(--ops-text);
  border: 1px solid var(--ops-line-strong); border-radius: var(--ops-radius);
  box-shadow: var(--ops-shadow);
}
.stSpinner > div { border-top-color: var(--ops-accent) !important; }

/* ---- ops components ------------------------------------------------------------------------ */
.ops-icon { display: inline-flex; vertical-align: -.18em; line-height: 1; }
.ops-icon svg { flex: none; }

.ops-hero { margin: .2rem 0 1.05rem; }
.ops-hero-row { display: flex; align-items: flex-start; gap: 14px; }
.ops-hero-icon {
  flex: none; width: 46px; height: 46px; border-radius: 13px;
  display: flex; align-items: center; justify-content: center;
  color: #fff;
  background: linear-gradient(135deg, #4F7CFF, #7C6CFF);
  box-shadow: var(--ops-glow);
}
.ops-eyebrow {
  font-size: .68rem; font-weight: 700; letter-spacing: .14em;
  text-transform: uppercase; color: var(--ops-accent); margin: 0 0 2px;
}
.ops-hero-title {
  font-size: 1.62rem; font-weight: 680; letter-spacing: -.02em;
  color: var(--ops-text); margin: 0; line-height: 1.15;
}
.ops-hero-sub { color: var(--ops-text-2); font-size: .93rem; margin: 6px 0 0; max-width: 74ch; }
.ops-hero-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }

.ops-chip {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: .72rem; font-weight: 600; letter-spacing: .02em;
  padding: .18rem .6rem; border-radius: 999px;
  background: var(--ops-surface-2); border: 1px solid var(--ops-line-strong);
  color: var(--ops-text-2); white-space: nowrap;
}
.ops-chip.ops-tone-accent { color: var(--ops-accent); border-color: rgba(91,140,255,.4); background: var(--ops-accent-soft); }
.ops-chip.ops-tone-success { color: var(--ops-success); border-color: rgba(52,211,153,.35); background: rgba(52,211,153,.1); }
.ops-chip.ops-tone-warning { color: var(--ops-warning); border-color: rgba(251,191,36,.35); background: rgba(251,191,36,.08); }
.ops-chip.ops-tone-danger { color: var(--ops-danger); border-color: rgba(248,113,113,.35); background: rgba(248,113,113,.08); }
.ops-chip.ops-tone-info { color: var(--ops-info); border-color: rgba(56,189,248,.35); background: rgba(56,189,248,.08); }
.ops-chip.ops-tone-ai { color: var(--ops-ai); border-color: rgba(167,139,250,.4); background: rgba(167,139,250,.1); }
.ops-mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: .78em; }

.ops-card {
  background: linear-gradient(180deg, rgba(23,30,48,.55), rgba(18,24,38,.85));
  border: 1px solid var(--ops-line);
  border-radius: var(--ops-radius-lg);
  padding: 1rem 1.1rem;
  box-shadow: var(--ops-shadow);
  transition: border-color .2s ease, transform .2s ease, box-shadow .2s ease;
  height: 100%;
}
.ops-card.ops-hover:hover {
  border-color: rgba(91,140,255,.45);
  transform: translateY(-2px);
  box-shadow: 0 16px 40px rgba(2,6,17,.55), 0 0 0 1px rgba(91,140,255,.18);
}
.ops-card-title {
  display: flex; align-items: center; gap: 8px;
  font-weight: 640; color: var(--ops-text); font-size: .98rem;
}
.ops-card-sub { color: var(--ops-text-3); font-size: .78rem; margin-top: 2px; }

.ops-metric-label {
  display: flex; align-items: center; gap: 7px;
  font-size: .72rem; font-weight: 650; letter-spacing: .09em;
  text-transform: uppercase; color: var(--ops-text-3); margin-bottom: 6px;
}
.ops-metric-value {
  font-size: 1.72rem; font-weight: 700; letter-spacing: -.02em;
  color: var(--ops-text); font-variant-numeric: tabular-nums; line-height: 1.05;
}
.ops-metric-delta { display: flex; align-items: center; gap: 6px; margin-top: 7px; font-size: .8rem; font-weight: 600; }
.ops-metric-delta.ops-good { color: var(--ops-success); }
.ops-metric-delta.ops-bad { color: var(--ops-danger); }
.ops-metric-delta.ops-neutral { color: var(--ops-text-3); }
.ops-metric-caption { color: var(--ops-text-3); font-size: .75rem; margin-top: 4px; }

.ops-sev-stripe { border-left: 3px solid var(--ops-sev, var(--ops-accent)); }

.ops-meter { height: 6px; border-radius: 99px; background: rgba(148,163,184,.14); overflow: hidden; }
.ops-meter > div {
  height: 100%; border-radius: 99px;
  background: linear-gradient(90deg, #4F7CFF, #7C6CFF);
}

.ops-empty {
  border: 1.5px dashed var(--ops-line-strong);
  border-radius: var(--ops-radius-lg);
  padding: 2.4rem 1.6rem; text-align: center;
  background: color-mix(in srgb, var(--ops-surface) 55%, transparent);
}
.ops-empty .ops-empty-icon {
  width: 54px; height: 54px; margin: 0 auto 12px; border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  color: var(--ops-accent); background: var(--ops-accent-soft);
}
.ops-empty-title { color: var(--ops-text); font-weight: 650; font-size: 1.04rem; margin-bottom: 4px; }
.ops-empty-body { color: var(--ops-text-2); font-size: .88rem; max-width: 52ch; margin: 0 auto; }

.ops-loading-bar {
  height: 4px; border-radius: 99px; overflow: hidden; margin: 10px 0;
  background: rgba(148,163,184,.12);
}
.ops-loading-bar > div {
  height: 100%; width: 38%; border-radius: 99px;
  background: linear-gradient(90deg, transparent, #5B8CFF, #7C6CFF, transparent);
  animation: ops-slide 1.15s ease-in-out infinite;
}
@keyframes ops-slide { 0% { transform: translateX(-120%);} 100% { transform: translateX(340%);} }
@keyframes ops-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(91,140,255,.45);} 50% { box-shadow: 0 0 0 6px rgba(91,140,255,0);} }

/* skeleton placeholders (content-shaped loading states) */
.ops-skeleton {
  position: relative; overflow: hidden;
  border-radius: var(--ops-radius-sm);
  background: rgba(148,163,184,.10);
}
.ops-skeleton::after {
  content: ""; position: absolute; inset: 0; transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, rgba(148,163,184,.16), transparent);
  animation: ops-shimmer 1.4s ease-in-out infinite;
}
@keyframes ops-shimmer { 100% { transform: translateX(100%); } }
.ops-skeleton-text { height: .72rem; margin: .55rem 0; }
.ops-skeleton-title { height: 1.05rem; width: 42%; margin-top: .2rem; }

/* horizontal workflow stepper (in-page progress visualization) */
.ops-stepper {
  display: flex; align-items: center; gap: 6px;
  flex-wrap: wrap; margin: .35rem 0 .8rem;
}
.ops-stepper-step {
  display: inline-flex; align-items: center; gap: 7px;
  padding: .32rem .72rem .32rem .42rem;
  border-radius: 999px; border: 1px solid var(--ops-line-strong);
  background: var(--ops-surface);
  font-size: .76rem; font-weight: 600; color: var(--ops-text-3);
  white-space: nowrap;
  transition: border-color .18s ease, background .18s ease, color .18s ease;
}
.ops-stepper-glyph {
  width: 17px; height: 17px; border-radius: 50%; flex: none;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: .6rem; font-weight: 700;
  background: var(--ops-surface-2); border: 1.5px solid var(--ops-line-strong);
}
.ops-stepper-glyph svg { display: block; }
.ops-stepper-step.ops-done {
  color: var(--ops-success); border-color: rgba(52,211,153,.4);
  background: rgba(52,211,153,.08);
}
.ops-stepper-step.ops-done .ops-stepper-glyph {
  border-color: var(--ops-success); background: rgba(52,211,153,.15); color: var(--ops-success);
}
.ops-stepper-step.ops-active {
  color: var(--ops-accent); border-color: rgba(91,140,255,.45);
  background: var(--ops-accent-soft);
  box-shadow: 0 0 0 1px rgba(91,140,255,.25);
}
.ops-stepper-step.ops-active .ops-stepper-glyph {
  border-color: var(--ops-accent); background: rgba(91,140,255,.16); color: var(--ops-accent);
}
.ops-stepper-step.ops-blocked {
  color: var(--ops-danger); border-color: rgba(248,113,113,.4);
  background: rgba(248,113,113,.07);
}
.ops-stepper-step.ops-blocked .ops-stepper-glyph {
  border-color: var(--ops-danger); background: rgba(248,113,113,.14); color: var(--ops-danger);
}
/* available = prerequisites met, action not taken yet */
.ops-stepper-step.ops-available {
  color: var(--ops-text); border-style: dashed;
  border-color: rgba(91,140,255,.5); background: transparent;
}
.ops-stepper-step.ops-available .ops-stepper-glyph {
  border-color: var(--ops-accent); color: var(--ops-accent);
}
.ops-stage-pulse {
  display: inline-flex; width: 8px; height: 8px; border-radius: 50%;
  background: var(--ops-accent);
  animation: ops-dot-pulse 1.1s ease-in-out infinite;
}
@keyframes ops-dot-pulse { 0%,100% { opacity: .35; } 50% { opacity: 1; } }
.ops-stepper-connector { flex: none; width: 15px; height: 1.5px; background: var(--ops-line-strong); }

/* ---- command center: signal posture ring ------------------------------------------------- */
.ops-posture { display: flex; gap: 18px; align-items: center; }
.ops-posture-ring {
  flex: none; width: 132px; height: 132px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--ops-shadow), inset 0 0 0 1px rgba(255,255,255,.05);
}
.ops-posture-hole {
  width: 104px; height: 104px; border-radius: 50%;
  background:
    radial-gradient(closest-side, var(--ops-surface) 78%, transparent 100%),
    linear-gradient(180deg, rgba(23,30,48,.6), rgba(18,24,38,.9));
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px;
}
.ops-posture-score {
  font-size: 2.15rem; font-weight: 740; letter-spacing: -.03em;
  color: var(--ops-text); font-variant-numeric: tabular-nums; line-height: 1;
}
.ops-posture-caption {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: .56rem; font-weight: 700; letter-spacing: .16em;
  color: var(--ops-text-3);
}
.ops-posture-band {
  font-size: 1.02rem; font-weight: 700; letter-spacing: .04em; margin: 2px 0 6px;
}
.ops-posture-side .ops-card-sub { max-width: 30ch; }

@media (max-width: 900px) {
  .ops-posture { flex-direction: column; text-align: center; }
  .ops-posture-side .ops-card-sub { max-width: none; }
}

/* ---- decision banner (AI recommends / human decides) -------------------------------------- */
.ops-decision-banner {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  border: 1px solid rgba(167,139,250,.4);
  border-radius: var(--ops-radius);
  background: linear-gradient(90deg, rgba(167,139,250,.12),
              rgba(91,140,255,.08) 60%, transparent);
  padding: .65rem 1rem; margin-bottom: .9rem;
}
.ops-decision-banner .ops-banner-ai {
  font-size: .72rem; font-weight: 750; letter-spacing: .14em;
  color: var(--ops-ai);
}
.ops-decision-banner .ops-banner-arrow { color: var(--ops-text-3); }
.ops-decision-banner .ops-banner-human {
  font-size: .72rem; font-weight: 750; letter-spacing: .14em;
  color: var(--ops-success);
}

/* ---- decision-recorded confirmation panel -------------------------------------------------- */
.ops-confirm {
  border: 1px solid rgba(52,211,153,.45);
  border-radius: var(--ops-radius-lg);
  background:
    radial-gradient(600px 200px at 10% -20%, rgba(52,211,153,.14), transparent 60%),
    linear-gradient(180deg, rgba(23,30,48,.55), rgba(18,24,38,.85));
  padding: 1.2rem 1.3rem; margin: .4rem 0 1rem;
}
.ops-confirm-badge {
  display: inline-flex; align-items: center; gap: 9px;
  font-size: 1.28rem; font-weight: 750; letter-spacing: .02em;
  color: var(--ops-success); margin-bottom: .35rem;
}

/* small live-status dot */
.ops-status-dot {
  width: 7px; height: 7px; border-radius: 50%;
  display: inline-flex; flex: none;
  background: #6B7A93;
}
.ops-status-dot.ops-tone-ai { background: #A78BFA; box-shadow: 0 0 8px rgba(167,139,250,.8); }
.ops-status-dot.ops-tone-success { background: var(--ops-success); box-shadow: 0 0 7px rgba(52,211,153,.7); }
.ops-status-dot.ops-tone-danger { background: var(--ops-danger); box-shadow: 0 0 7px rgba(248,113,113,.7); }

.ops-rail { display: flex; flex-direction: column; margin: 2px 0 4px; }
.ops-rail-step { display: flex; gap: 10px; position: relative; padding-bottom: 14px; }
.ops-rail-step:last-child { padding-bottom: 0; }
.ops-rail-step::before {
  content: ""; position: absolute; left: 10px; top: 22px; bottom: -2px;
  width: 2px; background: var(--ops-line);
}
.ops-rail-step:last-child::before { display: none; }
.ops-rail-dot {
  flex: none; width: 21px; height: 21px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: .62rem; font-weight: 700;
  background: var(--ops-surface-2); border: 1.5px solid var(--ops-line-strong);
  color: var(--ops-text-3); z-index: 1;
}
.ops-rail-step.ops-done .ops-rail-dot {
  background: rgba(52,211,153,.15); border-color: var(--ops-success); color: var(--ops-success);
}
.ops-rail-step.ops-active .ops-rail-dot {
  background: var(--ops-accent-soft); border-color: var(--ops-accent); color: var(--ops-accent);
  animation: ops-pulse 1.8s ease-in-out infinite;
}
.ops-rail-step.ops-blocked .ops-rail-dot {
  background: rgba(248,113,113,.12); border-color: var(--ops-danger); color: var(--ops-danger);
}
.ops-rail-step.ops-available .ops-rail-dot {
  background: transparent; border-style: dashed;
  border-color: var(--ops-accent); color: var(--ops-accent);
}
.ops-rail-label { font-size: .8rem; color: var(--ops-text-2); line-height: 1.25; padding-top: 2px; }
.ops-rail-step.ops-done .ops-rail-label { color: var(--ops-text); }
.ops-rail-step.ops-active .ops-rail-label { color: var(--ops-text); font-weight: 600; }
.ops-rail-step.ops-available .ops-rail-label { color: var(--ops-text); }
.ops-rail-hint { font-size: .68rem; color: var(--ops-text-3); }

.ops-timeline { display: flex; flex-direction: column; gap: 0; }
.ops-timeline-item { display: flex; gap: 12px; position: relative; padding-bottom: 14px; }
.ops-timeline-item:last-child { padding-bottom: 0; }
.ops-timeline-item::before {
  content: ""; position: absolute; left: 5px; top: 14px; bottom: -2px; width: 2px;
  background: var(--ops-line);
}
.ops-timeline-item:last-child::before { display: none; }
.ops-timeline-dot {
  flex: none; width: 11px; height: 11px; border-radius: 50%; margin-top: 5px;
  background: var(--ops-accent); box-shadow: 0 0 0 3px var(--ops-accent-soft); z-index: 1;
}
.ops-timeline-dot.ops-tone-success { background: var(--ops-success); box-shadow: 0 0 0 3px rgba(52,211,153,.16); }
.ops-timeline-dot.ops-tone-danger { background: var(--ops-danger); box-shadow: 0 0 0 3px rgba(248,113,113,.16); }
.ops-timeline-dot.ops-tone-warning { background: var(--ops-warning); box-shadow: 0 0 0 3px rgba(251,191,36,.14); }
.ops-timeline-dot.ops-tone-info { background: var(--ops-info); box-shadow: 0 0 0 3px rgba(56,189,248,.16); }
.ops-timeline-dot.ops-tone-ai { background: var(--ops-ai); box-shadow: 0 0 0 3px rgba(167,139,250,.18); }

.ops-kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; font-size: .84rem; }
.ops-kv dt { color: var(--ops-text-3); }
.ops-kv dd { margin: 0; color: var(--ops-text); font-variant-numeric: tabular-nums; text-align: right; }

.ops-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.ops-brand-mark {
  flex: none; width: 38px; height: 38px; border-radius: 11px;
  display: flex; align-items: center; justify-content: center; color: #fff;
  background: conic-gradient(from 210deg at 50% 50%, #4F7CFF, #7C6CFF, #38BDF8, #4F7CFF);
  box-shadow: 0 6px 20px rgba(91,124,255,.4), inset 0 0 0 1px rgba(255,255,255,.18);
}
.ops-brand-name { font-weight: 750; font-size: 1.06rem; letter-spacing: -.01em; color: var(--ops-text); }
.ops-brand-tagline { font-size: .64rem; letter-spacing: .16em; text-transform: uppercase; color: var(--ops-text-3); }

.ops-sidebar-card {
  background: color-mix(in srgb, var(--ops-surface) 80%, transparent);
  border: 1px solid var(--ops-line);
  border-radius: var(--ops-radius);
  padding: .7rem .8rem; margin: .45rem 0;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
  }
}
/* page transition: opacity-only crossfade (no layout shift, no transform),
   so reruns read as a smooth repaint instead of a flicker; disabled under
   prefers-reduced-motion by the rule above. */
@media (prefers-reduced-motion: no-preference) {
  .stMainBlockContainer { animation: ops-page-fade .18s ease-out both; }
}
@keyframes ops-page-fade { from { opacity: 0; } to { opacity: 1; } }
@media (max-width: 900px) {
  .block-container { padding-left: 4vw; padding-right: 4vw; }
  .ops-hero-title { font-size: 1.32rem; }
  .ops-metric-value { font-size: 1.4rem; }
}
"""


def apply_theme() -> None:
    """Inject the global stylesheet once per rerun."""
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)
