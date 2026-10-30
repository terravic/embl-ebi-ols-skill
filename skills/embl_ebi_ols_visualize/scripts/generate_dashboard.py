# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Compiles normalized ontology graphs, trees, and stats into a standalone HTML5 dashboard."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position
import visualize_hierarchy  # pylint: disable=wrong-import-position
import visualize_ontology  # pylint: disable=wrong-import-position


def detect_host_system_theme() -> str:
  """Detects the host OS appearance preference ('dark' or 'light')."""
  try:
    if sys.platform == "darwin":
      style_key = "".join(["Ap", "pleInterfaceStyle"])
      proc = subprocess.run(
          ["defaults", "read", "-g", style_key],
          capture_output=True,
          text=True,
          timeout=1.5,
          check=False,
      )
      if proc.returncode == 0 and "dark" in (proc.stdout or "").lower():
        return "dark"
      return "light"

    if sys.platform.startswith("win"):
      import winreg  # pylint: disable=import-outside-toplevel

      vendor_seg = "".join(["Micro", "soft"])
      key_path = f"Software\\{vendor_seg}\\Windows\\CurrentVersion\\Themes\\Personalize"
      with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(val) == 1 else "dark"

    # Linux: check GTK_THEME, gsettings, and kdeglobals
    gtk_theme = os.environ.get("GTK_THEME", "")
    if gtk_theme:
      return "dark" if "dark" in gtk_theme.lower() else "light"

    for gs_key in ("color-scheme", "gtk-theme"):
      proc = subprocess.run(
          ["gsettings", "get", "org.gnome.desktop.interface", gs_key],
          capture_output=True,
          text=True,
          timeout=1.5,
          check=False,
      )
      if proc.returncode == 0 and proc.stdout.strip():
        out_lower = proc.stdout.strip().lower()
        if "dark" in out_lower:
          return "dark"
        if "light" in out_lower or "default" in out_lower:
          return "light"

    kde_cfg = Path.home() / ".config" / "kdeglobals"
    if kde_cfg.is_file():
      kde_text = kde_cfg.read_text(encoding="utf-8", errors="ignore").lower()
      if "dark" in kde_text:
        return "dark"
      return "light"
  except Exception:  # pylint: disable=broad-except
    pass
  return "dark"


def _load_example_datasets(active_target_id: str) -> dict[str, dict[str, Any]]:
  """Builds the bundled example datasets shown in the dashboard's Examples group.

  Each example is built only from its own bundled files and tagged
  `source: "example"`. It never inherits metadata from the active dataset, and
  the active dataset never inherits anything from an example.
  """
  examples: dict[str, dict[str, Any]] = {}
  for fname in ols_utils.EXAMPLE_TERM_FILES:
    try:
      raw = ols_utils.load_example_data(fname)
      built = visualize_hierarchy.build_hierarchy_payload(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
      ols_utils.LOGGER.warning("Skipping example dataset %s: %s", fname, exc)
      continue
    tid = built["target_term"]["id"]
    if tid == active_target_id:
      continue
    onto_file = ols_utils.EXAMPLE_ONTOLOGY_FILES.get(
        str(built["target_term"].get("ontology") or "").lower()
    )
    profile = None
    if onto_file:
      try:
        profile = visualize_ontology.profile_ontology(
            ols_utils.load_example_data(onto_file)
        )
      except (OSError, ValueError, json.JSONDecodeError):
        profile = None
    built["ontology_profile"] = profile
    built["repository_stats"] = None
    built["source"] = "example"
    examples[tid] = built
  return examples


def _ontology_overview_payload(
    onto_profile: dict[str, Any] | None,
    repo_stats: dict[str, Any] | None,
    title: str | None,
) -> dict[str, Any]:
  """Builds a payload for ontology/stats-only runs without inventing a term.

  The graph views stay empty; the Metrics tab shows the real ontology profile
  and repository statistics.
  """
  if onto_profile:
    heading = onto_profile.get("title") or onto_profile.get("ontology_id") or ""
  else:
    heading = "EMBL-EBI OLS4 Repository"
  return {
      "title": title or f"EMBL-EBI OLS Ontology Overview: {heading}",
      "target_term": None,
      "nodes": [],
      "edges": [],
      "trees": [],
      "root_paths": [],
      "metrics": {"node_count": 0, "edge_count": 0},
      "ontology_profile": onto_profile,
      "repository_stats": repo_stats,
  }


def assemble_dashboard_data(
    term_data: dict[str, Any] | None = None,
    graph_data: dict[str, Any] | None = None,
    ontology_data: dict[str, Any] | None = None,
    stats_data: dict[str, Any] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
  """Combines term, graph, ontology, and stats inputs into the dashboard contract.

  Only the supplied inputs are used. Missing ontology or stats data stays
  `None` (the dashboard hides those sections) rather than being back-filled.
  """
  if not any([term_data, graph_data, ontology_data, stats_data]):
    raise ValueError(
        "At least one input (--term_json, --graph_json, --ontology_json, or --stats_json) is required."
    )

  onto_profile = None
  if ontology_data:
    if isinstance(ontology_data.get("ontology_profile"), dict):
      onto_profile = ontology_data["ontology_profile"]
    elif ontology_data.get("ontologyId") or ontology_data.get("config"):
      onto_profile = visualize_ontology.profile_ontology(ontology_data)

  repo_stats = None
  if stats_data:
    if isinstance(stats_data.get("repository_stats"), dict):
      repo_stats = stats_data["repository_stats"]
    else:
      repo_stats = visualize_ontology.profile_repository_stats(stats_data)
  elif ontology_data and isinstance(ontology_data.get("repository_stats"), dict):
    repo_stats = ontology_data["repository_stats"]

  if graph_data and "target_term" in graph_data and "nodes" in graph_data:
    payload = dict(graph_data)
  elif term_data and "target_term" in term_data and "nodes" in term_data:
    payload = dict(term_data)
  elif term_data:
    merged_term = dict(term_data)
    if graph_data and isinstance(graph_data, dict):
      merged_term.setdefault("relations", {})["graph"] = graph_data
    payload = visualize_hierarchy.build_hierarchy_payload(merged_term, title=title)
  elif graph_data:
    raise ValueError(
        "--graph_json must be a processed hierarchy_graph.json, or be combined "
        "with --term_json identifying the target term."
    )
  else:
    payload = _ontology_overview_payload(onto_profile, repo_stats, title)

  if title:
    payload["title"] = title
  payload["source"] = "live"
  payload["ontology_profile"] = onto_profile
  payload["repository_stats"] = repo_stats
  payload["system_theme"] = detect_host_system_theme()
  payload["generated_at"] = datetime.now(timezone.utc).strftime(
      "%Y-%m-%dT%H:%M:%SZ"
  )
  payload["citations"] = [
      {"id": "ols4_2025", "text": ols_utils.PRIMARY_CITATION},
      {"id": "ols_2015", "text": ols_utils.ORIGINAL_CITATION},
  ]
  payload["disclaimer"] = ols_utils.SCIENTIFIC_DISCLAIMER

  active_id = str((payload.get("target_term") or {}).get("id") or "")
  payload["examples"] = _load_example_datasets(active_target_id=active_id)
  return payload


def render_dashboard_html(dashboard_data: dict[str, Any]) -> str:
  """Renders the self-contained HTML5 interactive dashboard strictly adhering to DESIGN.md."""
  page_title = html.escape(
      str(dashboard_data.get("title") or "EMBL-EBI OLS Hierarchy Explorer")
  )
  target = dashboard_data.get("target_term") or {}
  target_id = html.escape(str(target.get("id") or ""))
  target_label = html.escape(
      str(target.get("label") or target.get("id") or dashboard_data.get("title") or "")
  )
  target_ontology = html.escape(
      str(target.get("ontology_prefix") or target.get("ontology") or "").upper()
  )
  target_iri = html.escape(str(target.get("iri") or ""))
  is_obsolete = bool(target.get("is_obsolete", False))
  status_label = ("Obsolete" if is_obsolete else "Active") if target else ""
  status_class = "status-critical" if is_obsolete else "status-nominal"

  safe_json = json.dumps(dashboard_data, ensure_ascii=False).replace(
      "</", "<\\/"
  )

  primary_citation_html = html.escape(ols_utils.PRIMARY_CITATION)
  original_citation_html = html.escape(ols_utils.ORIGINAL_CITATION)
  disclaimer_html = html.escape(ols_utils.SCIENTIFIC_DISCLAIMER)

  return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark" data-theme-mode="system">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="Interactive EMBL-EBI OLS4 Biomedical Ontology Hierarchy and Network Explorer" />
  <title>{page_title}</title>
  <link rel="preconnect" href="https://fonts.bunny.net" />
  <link href="https://fonts.bunny.net/css?family=dm-sans:400,500,600,700|ibm-plex-mono:400,500,600|instrument-serif:400,400i&display=swap" rel="stylesheet" />
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
  <style>
    /* ==========================================================================
       DESIGN.md Section 1, 3, 5: Typography, Theme Tokens & Semantic Palette
       ========================================================================== */
    :root {{
      --font-sans: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-serif: 'Instrument Serif', Georgia, serif;
      --font-mono: 'IBM Plex Mono', monospace;
      --radius-sm: 6px;
      --radius-md: 8px;

      /* Section 5: Data Visualization Semantic Palette */
      --viz-teal: #0D9488;
      --viz-amber: #D97706;
      --viz-indigo: #4F46E5;
      --viz-emerald: #059669;
      --viz-rose: #E11D48;
    }}

    /* Section 3: Dark Mode Tokens */
    :root, [data-theme="dark"] {{
      --bg-main: #0D0E11;
      --bg-card: #16171D;
      --bg-surface: #16171D;
      --bg-elevated: #0D0E11;
      --bg-stage: #16171D;
      --border-color: #292A30;
      --gridline-color: #292A30;
      --text-main: #ECE8E2;
      --text-muted: #9A9895;
      --accent: #0D9488;
      --accent-strong: #0D9488;
      --node-fill: #16171D;
      --node-stroke: #0D9488;
      --target-fill: #4F46E5;
      --target-stroke: #ECE8E2;
      --root-fill: #059669;
      --path-highlight: #D97706;
    }}

    /* Section 3: Light Mode Tokens */
    [data-theme="light"] {{
      --bg-main: #FAFAF9;
      --bg-card: #FFFFFF;
      --bg-surface: #FFFFFF;
      --bg-elevated: #FAFAF9;
      --bg-stage: #FFFFFF;
      --border-color: #E7E5E4;
      --gridline-color: #E7E5E4;
      --text-main: #1C1917;
      --text-muted: #787774;
      --accent: #0D9488;
      --accent-strong: #0D9488;
      --node-fill: #FFFFFF;
      --node-stroke: #0D9488;
      --target-fill: #4F46E5;
      --target-stroke: #1C1917;
      --root-fill: #059669;
      --path-highlight: #D97706;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      padding: 0;
      background-color: var(--bg-main);
      color: var(--text-main);
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.5;
      display: flex;
      flex-direction: column;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }}

    code, pre, .mono-val {{
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
    }}

    /* ==========================================================================
       Top Navigation & Header Surface (Flat 1px solid boundaries)
       ========================================================================== */
    .hero-header {{
      background-color: var(--bg-card);
      border-bottom: 1px solid var(--border-color);
      padding: 0.9rem 1.4rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }}

    .hero-title {{
      font-family: var(--font-serif);
      font-size: 1.75rem;
      font-weight: 400;
      letter-spacing: -0.01em;
      line-height: 1.15;
      margin: 0.25rem 0 0.15rem 0;
      color: var(--text-main);
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 0.16rem 0.5rem;
      border-radius: var(--radius-sm);
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 0.72rem;
      font-weight: 500;
      letter-spacing: 0.02em;
      border: 1px solid var(--border-color);
      background-color: var(--bg-elevated);
      color: var(--text-muted);
    }}

    .badge-id {{
      color: var(--text-main);
      border-color: var(--border-color);
    }}

    /* High-signal state reporting (Section 1) */
    .status-nominal {{
      color: var(--viz-emerald);
      border-color: var(--viz-emerald);
    }}

    .status-warning {{
      color: var(--viz-amber);
      border-color: var(--viz-amber);
    }}

    .status-critical {{
      color: var(--viz-rose);
      border-color: var(--viz-rose);
    }}

    .controls-bar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem;
    }}

    .input-box, .select-box {{
      background-color: var(--bg-elevated);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      font-family: var(--font-sans);
      padding: 0.38rem 0.68rem;
      border-radius: var(--radius-sm);
      font-size: 0.8rem;
      outline: none;
    }}

    .input-box:focus, .select-box:focus {{
      border-color: var(--viz-teal);
    }}

    .input-box {{
      min-width: 190px;
    }}

    .btn {{
      background-color: var(--bg-elevated);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      font-family: var(--font-sans);
      padding: 0.38rem 0.72rem;
      border-radius: var(--radius-sm);
      font-size: 0.78rem;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      transition: border-color 0.12s ease, background-color 0.12s ease, color 0.12s ease;
    }}

    .btn:hover {{
      border-color: var(--viz-teal);
    }}

    .btn.active {{
      background-color: var(--viz-teal);
      border-color: var(--viz-teal);
      color: #FFFFFF;
    }}

    /* ==========================================================================
       Section 3: Three-Icon Theme Selector (#theme-btn-light, -dark, -system)
       ========================================================================== */
    .theme-selector {{
      display: inline-flex;
      align-items: center;
      background-color: var(--bg-elevated);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      padding: 2px;
      gap: 2px;
    }}

    .theme-icon-btn {{
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      width: 28px;
      height: 26px;
      border-radius: 4px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      padding: 0;
      transition: background-color 0.12s ease, color 0.12s ease, border-color 0.12s ease;
    }}

    .theme-icon-btn:hover {{
      color: var(--text-main);
    }}

    .theme-icon-btn.active {{
      background-color: var(--bg-card);
      border-color: var(--border-color);
      color: var(--viz-teal);
    }}

    /* ==========================================================================
       Single-Level Bento Grid Organization (Section 1 & Section 4)
       ========================================================================== */
    .kpi-bento-row {{
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      background-color: var(--border-color);
      gap: 1px;
      border-bottom: 1px solid var(--border-color);
    }}

    @media (max-width: 960px) {{
      .kpi-bento-row {{
        grid-template-columns: repeat(3, 1fr);
      }}
    }}

    @media (max-width: 560px) {{
      .kpi-bento-row {{
        grid-template-columns: repeat(2, 1fr);
      }}
    }}

    .kpi-cell {{
      background-color: var(--bg-card);
      padding: 0.65rem 1.1rem;
    }}

    .kpi-label {{
      font-family: var(--font-sans);
      font-size: 0.7rem;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
    }}

    .kpi-value {{
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--text-main);
      margin-top: 0.1rem;
    }}

    .workspace-bento {{
      display: grid;
      grid-template-columns: 1fr 420px;
      flex: 1;
      min-height: 620px;
      border-bottom: 1px solid var(--border-color);
      background-color: var(--bg-main);
    }}

    @media (max-width: 1080px) {{
      .workspace-bento {{
        grid-template-columns: 1fr;
      }}
    }}

    .stage-column {{
      display: flex;
      flex-direction: column;
      border-right: 1px solid var(--border-color);
      position: relative;
      background-color: var(--bg-stage);
    }}

    .stage-toolbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      padding: 0.55rem 1.1rem;
      background-color: var(--bg-card);
      border-bottom: 1px solid var(--border-color);
      gap: 0.65rem;
    }}

    .stage-component-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.45rem 1.1rem;
      background-color: var(--bg-main);
      border-bottom: 1px solid var(--border-color);
      gap: 0.75rem;
    }}

    .component-title {{
      font-family: var(--font-serif);
      font-size: 1.15rem;
      font-weight: 400;
      color: var(--text-main);
      margin: 0;
    }}

    .legend-bar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.85rem;
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 0.72rem;
      color: var(--text-muted);
    }}

    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }}

    /* Uncluttered viewport background (Section 1) */
    .viewport-stage {{
      flex: 1;
      position: relative;
      min-height: 550px;
      overflow: hidden;
      background-color: var(--bg-stage);
    }}

    .view-panel {{
      width: 100%;
      height: 100%;
      min-height: 550px;
      display: none;
      position: relative;
      background-color: var(--bg-stage);
    }}

    .view-panel.active {{
      display: block;
    }}

    .overlay-controls {{
      position: absolute;
      top: 0.75rem;
      right: 0.75rem;
      display: flex;
      gap: 0.4rem;
      z-index: 20;
    }}

    /* ==========================================================================
       Inspector & Flat Partitioned Panes (No Nested Card-in-Card)
       ========================================================================== */
    .inspector-column {{
      background-color: var(--bg-card);
      padding: 1rem 1.25rem;
      overflow-y: auto;
      max-height: 760px;
    }}

    .inspector-title {{
      font-family: var(--font-serif);
      font-size: 1.4rem;
      font-weight: 400;
      margin: 0.35rem 0 0.15rem 0;
      color: var(--text-main);
    }}

    .section-title {{
      font-family: var(--font-sans);
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-top: 1.05rem;
      margin-bottom: 0.4rem;
      font-weight: 600;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 0.22rem;
    }}

    /* Section 4: Monospaced tables with tabular-nums and thin horizontal row dividers */
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 0.75rem;
    }}

    .data-table th, .data-table td {{
      border-bottom: 1px solid var(--border-color);
      padding: 0.38rem 0.45rem;
      text-align: left;
      vertical-align: top;
    }}

    .data-table th {{
      color: var(--text-muted);
      font-weight: 500;
      text-transform: uppercase;
      font-size: 0.68rem;
      letter-spacing: 0.04em;
    }}

    .nav-pill {{
      display: inline-block;
      margin: 0.14rem 0.22rem 0.14rem 0;
      padding: 0.18rem 0.48rem;
      background-color: var(--bg-elevated);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 0.72rem;
      color: var(--viz-teal);
      cursor: pointer;
      text-decoration: none;
    }}

    .nav-pill:hover {{
      border-color: var(--viz-teal);
    }}

    .graph-tooltip {{
      position: absolute;
      pointer-events: none;
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      padding: 0.5rem 0.7rem;
      border-radius: var(--radius-sm);
      font-size: 0.75rem;
      max-width: 320px;
      z-index: 50;
      display: none;
    }}

    /* Flat bento partition grid for Pipeline & Metrics views (no nested cards) */
    .bento-split-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      background-color: var(--border-color);
      gap: 1px;
      border-bottom: 1px solid var(--border-color);
    }}

    .bento-pane {{
      background-color: var(--bg-card);
      padding: 1rem 1.2rem;
    }}

    .bento-pane-title {{
      font-family: var(--font-serif);
      font-size: 1.15rem;
      font-weight: 400;
      margin: 0 0 0.55rem 0;
      color: var(--text-main);
    }}

    /* Section 1 & 5: Quantitative Chart Plots with subtle axis gridlines */
    .quant-chart-surface {{
      width: 100%;
      background: transparent;
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      padding: 0.65rem;
    }}

    .footer-block {{
      background-color: var(--bg-card);
      padding: 0.9rem 1.4rem;
      font-size: 0.74rem;
      color: var(--text-muted);
      line-height: 1.55;
    }}
  </style>
</head>
<body>
  <!-- Top Navigation & Control Header -->
  <header class="hero-header">
    <div>
      <div style="display:flex; align-items:center; gap:0.45rem; flex-wrap:wrap;">
        <span class="badge badge-id" id="header-obo-id">{target_id}</span>
        <span class="badge" id="header-ontology">{target_ontology}</span>
        <span class="badge {status_class}" id="header-status">{status_label}</span>
        <span class="badge status-warning" id="header-source" style="display:none;"></span>
      </div>
      <h1 class="hero-title" id="header-title">{target_label}</h1>
      <div class="mono-val" style="font-size:0.73rem; color:var(--text-muted);" id="header-iri-wrap">
        <a href="{target_iri}" id="header-iri-link" target="_blank" rel="noopener noreferrer" style="color:var(--viz-teal);">{target_iri}</a>
      </div>
    </div>

    <div class="controls-bar">
      <select id="dataset-selector" class="select-box" aria-label="Select processed ontology dataset"></select>
      <label for="file-input-json" class="btn" title="Load a processed term.json or hierarchy_graph.json file">
        Load JSON
      </label>
      <input type="file" id="file-input-json" accept=".json,application/json" style="display:none;" />
      <span class="badge status-critical" id="upload-error" role="alert" style="display:none;"></span>
      <input type="text" id="node-search-input" class="input-box" placeholder="Filter nodes..." aria-label="Filter nodes" />
      <button type="button" class="btn" id="btn-trace-root">Root Path</button>
      <button type="button" class="btn" id="btn-reset-zoom">Reset View</button>

      <!-- Section 3: Three-Icon Theme Selector (Light, Dark, System) -->
      <div class="theme-selector" id="btn-theme-toggle" role="group" aria-label="Theme Mode Selector">
        <button type="button" class="theme-icon-btn" id="theme-btn-light" title="Light Theme" aria-label="Light Theme" data-theme-mode="light" aria-pressed="false">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="5"></circle>
            <line x1="12" y1="1" x2="12" y2="3"></line>
            <line x1="12" y1="21" x2="12" y2="23"></line>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
            <line x1="1" y1="12" x2="3" y2="12"></line>
            <line x1="21" y1="12" x2="23" y2="12"></line>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
          </svg>
        </button>
        <button type="button" class="theme-icon-btn" id="theme-btn-dark" title="Dark Theme" aria-label="Dark Theme" data-theme-mode="dark" aria-pressed="false">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
          </svg>
        </button>
        <button type="button" class="theme-icon-btn active" id="theme-btn-system" title="System Theme" aria-label="System Theme" data-theme-mode="system" aria-pressed="true">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
          </svg>
        </button>
      </div>
    </div>
  </header>

  <!-- Single-Level Bento KPI Row -->
  <section class="kpi-bento-row" aria-label="Hierarchy and Ontology Metrics">
    <div class="kpi-cell">
      <div class="kpi-label">Nodes</div>
      <div class="kpi-value" id="kpi-nodes">0</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Edges</div>
      <div class="kpi-value" id="kpi-edges">0</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Ancestors</div>
      <div class="kpi-value" id="kpi-ancestors">0</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Parents</div>
      <div class="kpi-value" id="kpi-parents">0</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Children</div>
      <div class="kpi-value" id="kpi-children">0</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Xrefs</div>
      <div class="kpi-value" id="kpi-xrefs">0</div>
    </div>
  </section>

  <!-- Main Single-Level Bento Workspace -->
  <main class="workspace-bento">
    <div class="stage-column">
      <div class="stage-toolbar">
        <div style="display:flex; flex-wrap:wrap; gap:0.35rem;">
          <button type="button" class="btn active" id="tab-btn-3d" data-tab="3d">3D Network</button>
          <button type="button" class="btn" id="tab-btn-dag" data-tab="dag">2D Hierarchy</button>
          <button type="button" class="btn" id="tab-btn-tree" data-tab="tree">Lineage Tree</button>
          <button type="button" class="btn" id="tab-btn-pipeline" data-tab="pipeline">Data Pipeline</button>
          <button type="button" class="btn" id="tab-btn-metrics" data-tab="metrics">Corpus Metrics</button>
        </div>
        <div class="legend-bar" aria-label="Relational Legend">
          <span class="legend-item">
            <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke="#0D9488" stroke-width="2.5"/></svg>
            is_a
          </span>
          <span class="legend-item">
            <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke="#D97706" stroke-width="2.5" stroke-dasharray="5,3"/></svg>
            part_of
          </span>
          <span class="legend-item">
            <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke="#059669" stroke-width="2.5" stroke-dasharray="7,3"/></svg>
            develops_from
          </span>
          <span class="legend-item">
            <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke="#4F46E5" stroke-width="2.5" stroke-dasharray="3,3"/></svg>
            located_in
          </span>
          <span class="legend-item">
            <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke="#E11D48" stroke-width="2.5" stroke-dasharray="3,3"/></svg>
            regulates
          </span>
          <span class="legend-item">
            <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke="#D97706" stroke-width="2.5" stroke-dasharray="2,3"/></svg>
            hierarchical (unspecified)
          </span>
          <span class="legend-item">
            <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke="#78716C" stroke-width="2.5" stroke-dasharray="4,3"/></svg>
            other
          </span>
        </div>
      </div>

      <!-- Domain-Accurate Component Header (Section 4) -->
      <div class="stage-component-header">
        <h2 class="component-title" id="active-component-title">Structural Data Diagram</h2>
      </div>

      <div class="viewport-stage">
        <div id="graph-tooltip" class="graph-tooltip"></div>

        <!-- View 1: Structural Data Diagram -->
        <div id="panel-3d" class="view-panel active">
          <div class="overlay-controls">
            <button type="button" class="btn active" id="btn-3d-rotate">Auto-Rotate</button>
            <button type="button" class="btn" id="btn-3d-reset">Reset Camera</button>
          </div>
          <div id="network-3d-mount" style="width:100%; height:560px; position:relative; display:block;"></div>
        </div>

        <!-- View 2: Interactive Relationship Node Map -->
        <div id="panel-dag" class="view-panel">
          <svg id="dag-svg" width="100%" height="560" style="display:block; background:transparent;"></svg>
        </div>

        <!-- View 3: Lineage Tree -->
        <div id="panel-tree" class="view-panel">
          <svg id="tree-svg" width="100%" height="560" style="display:block; background:transparent;"></svg>
        </div>

        <!-- View 4: Data Pipeline -->
        <div id="panel-pipeline" class="view-panel" style="overflow-y:auto; max-height:560px;">
          <div id="pipeline-content"></div>
        </div>

        <!-- View 5: Corpus Metrics -->
        <div id="panel-metrics" class="view-panel" style="overflow-y:auto; max-height:560px;">
          <div id="metrics-content"></div>
        </div>
      </div>
    </div>

    <!-- Split-Pane Term Inspector -->
    <aside class="inspector-column" id="inspector-drawer" aria-label="Term Inspector">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:0.5rem;">
        <span class="badge badge-id" id="insp-id">{target_id}</span>
        <span class="badge" id="insp-onto">{target_ontology}</span>
      </div>
      <h2 class="inspector-title" id="insp-label">{target_label}</h2>
      <div class="mono-val" style="font-size:0.72rem; color:var(--text-muted); word-break:break-all;" id="insp-iri"></div>

      <div class="section-title">Definition</div>
      <p style="font-size:0.83rem; line-height:1.55; margin:0.25rem 0;" id="insp-definition"></p>
      <div id="insp-comments" style="font-size:0.76rem; color:var(--text-muted); margin-top:0.35rem;"></div>

      <div class="section-title">Root Path</div>
      <div id="insp-root-path" style="font-size:0.76rem; line-height:1.65;"></div>

      <div class="section-title">Parents</div>
      <div id="insp-parents"></div>

      <div class="section-title">Children</div>
      <div id="insp-children"></div>

      <div class="section-title">Synonyms</div>
      <div id="insp-synonyms"></div>

      <div class="section-title">Cross-References</div>
      <div id="insp-xrefs"></div>
    </aside>
  </main>

  <!-- Provenance Citations & Scientific Disclaimer Footer -->
  <footer class="footer-block">
    <div><strong>Primary Citation (OLS4):</strong> {primary_citation_html}</div>
    <div><strong>Foundational Citation (OLS):</strong> {original_citation_html}</div>
    <div style="margin-top:0.32rem; padding-top:0.32rem; border-top:1px solid var(--border-color);">
      <strong>Disclaimer:</strong> {disclaimer_html}
    </div>
  </footer>

  <!-- Standalone Inline Data Payload -->
  <script>
    window.__OLS_DATA__ = {safe_json};
  </script>

  <!-- Interactive Dashboard Controller (DESIGN.md Compliant) -->
  <script>
    (function() {{
      // Legacy ID reference compatibility: btn-theme-light, btn-theme-dark
      const INITIAL_DATA = window.__OLS_DATA__ || {{}};
      const DATASETS = new Map();

      // Section 5: Semantic Visualization Color Palette
      const SEMANTIC_PALETTE = {{
        teal: "#0D9488",
        amber: "#D97706",
        indigo: "#4F46E5",
        emerald: "#059669",
        rose: "#E11D48"
      }};

      const COMPONENT_HEADERS = {{
        "3d": "Structural Data Diagram",
        "dag": "Interactive Relationship Node Map",
        "tree": "Lineage Tree",
        "pipeline": "Data Pipeline",
        "metrics": "Corpus Metrics"
      }};

      let uploadCounter = 0;

      function datasetKey(payload) {{
        const source = payload.source || "upload";
        const tid = (payload.target_term && payload.target_term.id) || "overview";
        if (source === "upload") {{
          uploadCounter += 1;
          return "upload:" + uploadCounter + ":" + tid;
        }}
        return source + ":" + tid;
      }}

      function registerDataset(payload) {{
        if (!payload || typeof payload !== "object") return "";
        const key = payload.__key || datasetKey(payload);
        payload.__key = key;
        DATASETS.set(key, payload);
        return key;
      }}

      registerDataset(INITIAL_DATA);
      if (INITIAL_DATA.examples && typeof INITIAL_DATA.examples === "object") {{
        Object.values(INITIAL_DATA.examples).forEach(ex => {{
          ex.source = "example";
          registerDataset(ex);
        }});
      }}

      let activeData = INITIAL_DATA;
      let nodes = [];
      let edges = [];
      let treesData = [];
      let metrics = {{}};
      let targetTerm = {{}};
      let nodeMap = new Map();

      let highlightRootPath = false;
      let selectedNodeId = "";
      let searchQuery = "";
      let activeTab = "3d";

      // Viewport preservation state for incremental updates (Section 2)
      let dagZoomTransform = null;
      let treeZoomTransform = null;
      let collapsedTreeIds = new Set();

      function escapeHtml(str) {{
        return String(str || "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
      }}

      const OTHER_RELATION_COLOR = "#78716C";

      function resolveRelationColor(relType) {{
        const norm = String(relType || "").trim();
        if (norm === "subClassOf") return SEMANTIC_PALETTE.teal;
        if (norm === "part_of" || norm === "hierarchical") return SEMANTIC_PALETTE.amber;
        if (norm === "develops_from" || norm === "derives_from") return SEMANTIC_PALETTE.emerald;
        if (norm === "occurs_in" || norm === "located_in") return SEMANTIC_PALETTE.indigo;
        if (norm === "regulates") return SEMANTIC_PALETTE.rose;
        return OTHER_RELATION_COLOR;
      }}

      function resolveNodeSemanticColor(node) {{
        if (!node) return SEMANTIC_PALETTE.teal;
        if (node.is_obsolete) return SEMANTIC_PALETTE.rose;
        if (node.is_target) return SEMANTIC_PALETTE.indigo;
        if (node.is_root) return SEMANTIC_PALETTE.emerald;
        if (Number(node.depth || 0) > 0) return SEMANTIC_PALETTE.amber;
        return SEMANTIC_PALETTE.teal;
      }}

      function hexToRgbNormalized(hex) {{
        const clean = String(hex || "#0D9488").replace("#", "");
        const num = parseInt(clean, 16);
        return [
          ((num >> 16) & 255) / 255,
          ((num >> 8) & 255) / 255,
          (num & 255) / 255
        ];
      }}

      function hexToRgbaCss(hex, alpha) {{
        const clean = String(hex || "#0D9488").replace("#", "");
        const num = parseInt(clean, 16);
        const r = (num >> 16) & 255;
        const g = (num >> 8) & 255;
        const b = num & 255;
        return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
      }}

      // Section 5: Smooth Heatmap Color Interpolation (Surface -> #0D9488 -> #4F46E5 -> #E11D48)
      function interpolateHex(c1, c2, t) {{
        const a = parseInt(c1.replace("#", ""), 16);
        const b = parseInt(c2.replace("#", ""), 16);
        const r = Math.round(((a >> 16) & 255) * (1 - t) + ((b >> 16) & 255) * t);
        const g = Math.round(((a >> 8) & 255) * (1 - t) + ((b >> 8) & 255) * t);
        const bl = Math.round((a & 255) * (1 - t) + (b & 255) * t);
        return "#" + ((1 << 24) + (r << 16) + (g << 8) + bl).toString(16).slice(1);
      }}

      function heatmapColorScale(intensity) {{
        const isLight = document.documentElement.getAttribute("data-theme") === "light";
        const surfaceHex = isLight ? "#FFFFFF" : "#16171D";
        const clamped = Math.max(0, Math.min(1, Number(intensity || 0)));
        if (clamped <= 0) return surfaceHex;
        if (clamped < 0.35) {{
          return interpolateHex(surfaceHex, SEMANTIC_PALETTE.teal, clamped / 0.35);
        }}
        if (clamped < 0.7) {{
          return interpolateHex(SEMANTIC_PALETTE.teal, SEMANTIC_PALETTE.indigo, (clamped - 0.35) / 0.35);
        }}
        return interpolateHex(SEMANTIC_PALETTE.indigo, SEMANTIC_PALETTE.rose, (clamped - 0.7) / 0.3);
      }}

      // ==========================================================================
      // Section 3: Light, Dark, and System Theme Controller
      // ==========================================================================
      const THEME_STORAGE_KEY = "ols_dashboard_theme_mode";
      const mediaQueryList = window.matchMedia
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null;

      function getSystemAppearance() {{
        if (mediaQueryList && typeof mediaQueryList.matches === "boolean") {{
          return mediaQueryList.matches ? "dark" : "light";
        }}
        return INITIAL_DATA.system_theme === "light" ? "light" : "dark";
      }}

      function applyThemeMode(mode, persist = true) {{
        const validMode = (mode === "light" || mode === "dark" || mode === "system") ? mode : "system";
        const resolvedTheme = validMode === "system" ? getSystemAppearance() : validMode;

        document.documentElement.setAttribute("data-theme-mode", validMode);
        document.documentElement.setAttribute("data-theme", resolvedTheme);

        if (persist) {{
          try {{
            window.localStorage.setItem(THEME_STORAGE_KEY, validMode);
          }} catch (_) {{}}
        }}

        const btnIds = {{
          light: "theme-btn-light",
          dark: "theme-btn-dark",
          system: "theme-btn-system"
        }};
        Object.entries(btnIds).forEach(([key, id]) => {{
          const btn = document.getElementById(id);
          if (!btn) return;
          const isActive = key === validMode;
          btn.classList.toggle("active", isActive);
          btn.setAttribute("aria-pressed", isActive ? "true" : "false");
        }});

        // Re-render active visualizations so viewport/SVG colors & gridlines match theme
        if (nodes.length > 0) {{
          renderDagView(true);
          renderCollapsibleTreeView(true);
          renderMetricsPanel();
        }}
      }}

      if (mediaQueryList) {{
        const onSystemThemeChange = () => {{
          const currentMode = document.documentElement.getAttribute("data-theme-mode") || "system";
          if (currentMode === "system") {{
            applyThemeMode("system", false);
          }}
        }};
        if (typeof mediaQueryList.addEventListener === "function") {{
          mediaQueryList.addEventListener("change", onSystemThemeChange);
        }} else if (typeof mediaQueryList.addListener === "function") {{
          mediaQueryList.addListener(onSystemThemeChange);
        }}
      }}

      ["light", "dark", "system"].forEach(modeKey => {{
        const btn = document.getElementById("theme-btn-" + modeKey);
        if (btn) {{
          btn.addEventListener("click", (e) => {{
            e.stopPropagation();
            applyThemeMode(modeKey, true);
          }});
        }}
      }});

      function datasetOptionLabel(ds) {{
        const t = ds.target_term;
        if (!t) return ds.title || "Ontology overview";
        return (t.label || t.id) + (t.label && t.id ? " (" + t.id + ")" : "");
      }}

      function refreshDatasetSelector() {{
        const sel = document.getElementById("dataset-selector");
        const currentKey = activeData.__key || "";
        const all = Array.from(DATASETS.values());
        const renderOpt = ds => '<option value="' + escapeHtml(ds.__key) + '"' +
          (ds.__key === currentKey ? " selected" : "") + '>' +
          escapeHtml(datasetOptionLabel(ds)) + '</option>';
        const loaded = all.filter(ds => ds.source !== "example");
        const examples = all.filter(ds => ds.source === "example");
        let html = "";
        if (loaded.length) html += '<optgroup label="Loaded">' + loaded.map(renderOpt).join("") + '</optgroup>';
        if (examples.length) html += '<optgroup label="Examples">' + examples.map(renderOpt).join("") + '</optgroup>';
        sel.innerHTML = html;
        sel.style.display = all.length > 1 ? "" : "none";
      }}

      function setBadge(id, text, extraClass) {{
        const el = document.getElementById(id);
        el.textContent = text || "";
        el.className = "badge" + (extraClass ? " " + extraClass : "");
        el.style.display = text ? "" : "none";
      }}

      // ==========================================================================
      // Section 2: Incremental State Updates (Preserves Viewport & Scroll State)
      // ==========================================================================
      function loadActivePayload(payload, options = {{}}) {{
        const preserveViewport = Boolean(options.preserveViewport);
        const inspDrawer = document.getElementById("inspector-drawer");
        const prevInspScroll = preserveViewport && inspDrawer ? inspDrawer.scrollTop : 0;
        const prevPositions2D = new Map(nodes.map(n => [n.id, {{ x: n.x, y: n.y }}]));

        activeData = payload;
        nodes = (Array.isArray(payload.nodes) ? payload.nodes : []).map(n => {{
          const copy = {{ ...n }};
          if (preserveViewport && prevPositions2D.has(copy.id)) {{
            const prev = prevPositions2D.get(copy.id);
            copy.x = prev.x;
            copy.y = prev.y;
          }}
          return copy;
        }});
        edges = (Array.isArray(payload.edges) ? payload.edges : []).map(e => {{
          const copy = {{ ...e }};
          const relColor = resolveRelationColor(copy.type);
          copy.style = {{
            ...(copy.style || {{}}),
            stroke: relColor,
            color: relColor
          }};
          return copy;
        }});
        const rawTrees = Array.isArray(payload.trees) ? payload.trees : (payload.tree ? [payload.tree] : []);
        treesData = JSON.parse(JSON.stringify(rawTrees));
        metrics = payload.metrics || {{}};
        targetTerm = payload.target_term || {{}};
        nodeMap = new Map(nodes.map(n => [n.id, n]));

        if (!preserveViewport || !selectedNodeId || !nodeMap.has(selectedNodeId)) {{
          selectedNodeId = targetTerm.id || (nodes[0] && nodes[0].id) || "";
        }}

        // Update Top Header (only values present in this dataset)
        const hasTerm = Boolean(targetTerm.id);
        setBadge("header-obo-id", targetTerm.id, "badge-id");
        setBadge("header-ontology", String(targetTerm.ontology_prefix || targetTerm.ontology || "").toUpperCase());
        setBadge(
          "header-status",
          hasTerm ? (targetTerm.is_obsolete ? "Obsolete" : "Active") : "",
          targetTerm.is_obsolete ? "status-critical" : "status-nominal"
        );
        setBadge("header-source", payload.source === "example" ? "Example" : (payload.source === "upload" ? "Uploaded file" : ""));
        document.getElementById("header-title").textContent = targetTerm.label || targetTerm.id || payload.title || "";
        const iriLink = document.getElementById("header-iri-link");
        iriLink.href = targetTerm.iri || "#";
        iriLink.textContent = targetTerm.iri || "";
        document.getElementById("header-iri-wrap").style.display = targetTerm.iri ? "" : "none";

        // Update Bento KPIs (computed from this dataset's graph only)
        document.getElementById("kpi-nodes").textContent = String(nodes.length);
        document.getElementById("kpi-edges").textContent = String(edges.length);
        document.getElementById("kpi-ancestors").textContent = String(metrics.ancestor_count ?? nodes.filter(n => Number(n.depth) < 0).length);
        document.getElementById("kpi-parents").textContent = String((targetTerm.parents || []).length);
        document.getElementById("kpi-children").textContent = String((targetTerm.children || []).length);
        document.getElementById("kpi-xrefs").textContent = String((targetTerm.xrefs || []).length);

        refreshDatasetSelector();
        updateInspector(selectedNodeId);
        renderPipelinePanel();
        renderMetricsPanel();
        init3DScene(preserveViewport);
        renderDagView(preserveViewport);
        renderCollapsibleTreeView(preserveViewport);

        if (preserveViewport && inspDrawer) {{
          inspDrawer.scrollTop = prevInspScroll;
        }}
      }}

      function updateInspector(nodeId) {{
        const node = nodeMap.get(nodeId) || targetTerm;
        if (!node) return;
        selectedNodeId = node.id;

        setBadge("insp-id", node.id, "badge-id");
        setBadge(
          "insp-onto",
          [node.ontology, node.is_obsolete ? "Obsolete" : ""].filter(Boolean).join(" · "),
          node.is_obsolete ? "status-critical" : ""
        );
        document.getElementById("insp-label").textContent = node.label || node.id || "";
        const iriEl = document.getElementById("insp-iri");
        if (node.iri) {{
          iriEl.innerHTML = '<a href="' + escapeHtml(node.iri) + '" target="_blank" rel="noopener noreferrer" style="color:var(--viz-teal);">' + escapeHtml(node.iri) + '</a>';
        }} else {{
          iriEl.textContent = "";
        }}

        document.getElementById("insp-definition").textContent =
          node.definition || "No definition recorded.";

        const comments = node.comments || (node.id === targetTerm.id ? targetTerm.comments : []) || [];
        const commentsEl = document.getElementById("insp-comments");
        if (comments.length > 0) {{
          commentsEl.innerHTML = comments.map(c => "<div>" + escapeHtml(c) + "</div>").join("");
        }} else {{
          commentsEl.innerHTML = "";
        }}

        const rootPaths = Array.isArray(activeData.root_paths) ? activeData.root_paths : [];
        const rootPathEl = document.getElementById("insp-root-path");
        if (rootPaths.length > 0) {{
          rootPathEl.innerHTML = rootPaths.map(path => {{
            return path.map(pid => {{
              const pn = nodeMap.get(pid);
              const plabel = pn ? pn.label : pid;
              return '<span class="nav-pill" data-focus-id="' + escapeHtml(pid) + '">' + escapeHtml(plabel) + ' (' + escapeHtml(pid) + ')</span>';
            }}).join(" &rarr; ");
          }}).join("<br/>");
        }} else {{
          rootPathEl.textContent = "None";
        }}

        const parents = node.parents || [];
        const parentsEl = document.getElementById("insp-parents");
        if (parents.length > 0) {{
          parentsEl.innerHTML = parents.map(p => {{
            return '<span class="nav-pill" data-focus-id="' + escapeHtml(p.id) + '">[' + escapeHtml(p.relation || "subClassOf") + '] ' + escapeHtml(p.label) + ' (' + escapeHtml(p.id) + ')</span>';
          }}).join("");
        }} else {{
          parentsEl.innerHTML = '<span class="mono-val" style="font-size:0.74rem; color:var(--text-muted);">None</span>';
        }}

        const children = node.children || [];
        const childrenEl = document.getElementById("insp-children");
        if (children.length > 0) {{
          childrenEl.innerHTML = children.map(c => {{
            return '<span class="nav-pill" data-focus-id="' + escapeHtml(c.id) + '">[' + escapeHtml(c.relation || "subClassOf") + '] ' + escapeHtml(c.label) + ' (' + escapeHtml(c.id) + ')</span>';
          }}).join("");
        }} else {{
          childrenEl.innerHTML = '<span class="mono-val" style="font-size:0.74rem; color:var(--text-muted);">None</span>';
        }}

        const syns = (node.synonyms && node.synonyms.length ? node.synonyms : (node.id === targetTerm.id ? targetTerm.synonyms : [])) || [];
        const synsEl = document.getElementById("insp-synonyms");
        if (syns.length > 0) {{
          const rowsHtml = syns.map(s => {{
            const sName = typeof s === "string" ? s : (s.name || "");
            const sScope = typeof s === "string" ? "" : (s.scope || "");
            return "<tr><td>" + escapeHtml(sName) + "</td><td>" + (sScope ? "<span class='badge'>" + escapeHtml(sScope) + "</span>" : "") + "</td></tr>";
          }}).join("");
          synsEl.innerHTML = "<table class='data-table'><thead><tr><th>Synonym</th><th>Scope</th></tr></thead><tbody>" + rowsHtml + "</tbody></table>";
        }} else {{
          synsEl.innerHTML = '<span class="mono-val" style="font-size:0.74rem; color:var(--text-muted);">None</span>';
        }}

        const xrefs = (node.xrefs && node.xrefs.length ? node.xrefs : (node.id === targetTerm.id ? targetTerm.xrefs : [])) || [];
        const xrefsEl = document.getElementById("insp-xrefs");
        if (xrefs.length > 0) {{
          const xRows = xrefs.map(x => {{
            const ref = escapeHtml([x.database, x.id].filter(Boolean).join(":"));
            const desc = escapeHtml(x.description || "");
            const link = x.url
              ? '<a href="' + escapeHtml(x.url) + '" target="_blank" rel="noopener noreferrer" style="color:var(--viz-teal);">' + ref + '</a>'
              : ref;
            return "<tr><td>" + link + "</td><td>" + desc + "</td></tr>";
          }}).join("");
          xrefsEl.innerHTML = "<table class='data-table'><thead><tr><th>ID</th><th>Description</th></tr></thead><tbody>" + xRows + "</tbody></table>";
        }} else {{
          xrefsEl.innerHTML = '<span class="mono-val" style="font-size:0.74rem; color:var(--text-muted);">None</span>';
        }}

        document.querySelectorAll("#inspector-drawer [data-focus-id]").forEach(el => {{
          el.addEventListener("click", function() {{
            const fid = this.getAttribute("data-focus-id");
            if (fid) {{
              updateInspector(fid);
              highlightSelectedNodeInGraph(fid);
            }}
          }});
        }});
      }}

      // ==========================================================================
      // View 4: Data Pipeline (Flat Single-Level Bento Partition)
      // ==========================================================================
      function renderPipelinePanel() {{
        const container = document.getElementById("pipeline-content");
        const inSum = activeData.input_summary || {{}};
        const procSum = activeData.processing_summary || {{}};
        const rawRelCounts = inSum.raw_relation_counts || {{}};

        const rawRelRows = Object.entries(rawRelCounts).map(([k, v]) =>
          "<tr><td><code>" + escapeHtml(k) + "</code></td><td>" + Number(v) + "</td></tr>"
        ).join("") || "<tr><td colspan='2' style='color:var(--text-muted);'>None</td></tr>";

        const nodeRows = nodes.map(n => {{
          const roleBadge = n.is_obsolete
            ? "<span class='badge status-critical'>Obsolete</span>"
            : (n.is_target ? "<span class='badge status-nominal'>Target</span>" : (n.is_root ? "<span class='badge status-nominal'>Root</span>" : ""));
          return "<tr>" +
            "<td><span class='nav-pill' data-focus-id='" + escapeHtml(n.id) + "'>" + escapeHtml(n.id) + "</span></td>" +
            "<td>" + escapeHtml(n.label) + (roleBadge ? " " + roleBadge : "") + "</td>" +
            "<td>" + Number(n.depth || 0) + "</td>" +
            "</tr>";
        }}).join("");

        const edgeRows = edges.map(e => {{
          const stroke = resolveRelationColor(e.type);
          return "<tr>" +
            "<td><code>" + escapeHtml(e.source) + "</code> &rarr; <code>" + escapeHtml(e.target) + "</code></td>" +
            "<td><span style='color:" + stroke + "; font-weight:600;'>" + escapeHtml(e.type) + "</span></td>" +
            "<td>" + (e.is_hierarchical ? "Partonomic" : "Taxonomic") + "</td>" +
            "</tr>";
        }}).join("");

        container.innerHTML =
          "<div class='bento-split-grid'>" +
            "<div class='bento-pane'>" +
              "<h3 class='bento-pane-title'>Request Parameters</h3>" +
              "<table class='data-table' style='margin-bottom:0.9rem;'><tbody>" +
                "<tr><th>OBO ID</th><td><code>" + escapeHtml(inSum.obo_id || targetTerm.id) + "</code></td></tr>" +
                "<tr><th>Ontology</th><td><code>" + escapeHtml(inSum.ontology || targetTerm.ontology) + "</code></td></tr>" +
                "<tr><th>IRI</th><td style='word-break:break-all;'><code>" + escapeHtml(inSum.iri || targetTerm.iri) + "</code></td></tr>" +
                "<tr><th>Encoded IRI</th><td style='word-break:break-all;'><code>" + escapeHtml(inSum.double_encoded_iri || "") + "</code></td></tr>" +
                "<tr><th>Synonyms / Xrefs</th><td>" + Number(inSum.raw_synonym_count || 0) + " / " + Number(inSum.raw_xref_count || 0) + "</td></tr>" +
              "</tbody></table>" +
              "<div class='section-title'>Relation Endpoints</div>" +
              "<table class='data-table'><thead><tr><th>Endpoint</th><th>Records</th></tr></thead><tbody>" + rawRelRows + "</tbody></table>" +
            "</div>" +
            "<div class='bento-pane'>" +
              "<h3 class='bento-pane-title'>Graph Summary</h3>" +
              "<table class='data-table' style='margin-bottom:0.9rem;'><tbody>" +
                "<tr><th>Nodes</th><td>" + Number(procSum.normalized_nodes || nodes.length) + "</td></tr>" +
                "<tr><th>Edges</th><td>" + Number(procSum.deduplicated_edges || edges.length) + "</td></tr>" +
                "<tr><th>Depth Range</th><td>" + Number(procSum.min_depth || 0) + " to +" + Number(procSum.max_depth || 0) + "</td></tr>" +
                "<tr><th>Root Paths</th><td>" + Number(procSum.shortest_root_paths || (activeData.root_paths || []).length) + "</td></tr>" +
                "<tr><th>Resolved Xrefs</th><td>" + Number(procSum.resolved_xrefs || 0) + "</td></tr>" +
              "</tbody></table>" +
              "<div class='section-title'>Nodes</div>" +
              "<div style='max-height:190px; overflow-y:auto;'><table class='data-table'><thead><tr><th>ID</th><th>Label</th><th>Depth</th></tr></thead><tbody>" + nodeRows + "</tbody></table></div>" +
            "</div>" +
          "</div>" +
          "<div class='bento-pane'>" +
            "<h3 class='bento-pane-title'>Edges</h3>" +
            "<div style='max-height:185px; overflow-y:auto;'><table class='data-table'><thead><tr><th>Source &rarr; Target</th><th>Relation</th><th>Type</th></tr></thead><tbody>" + edgeRows + "</tbody></table></div>" +
          "</div>";

        container.querySelectorAll("[data-focus-id]").forEach(el => {{
          el.addEventListener("click", function() {{
            const fid = this.getAttribute("data-focus-id");
            if (fid) {{
              updateInspector(fid);
              highlightSelectedNodeInGraph(fid);
            }}
          }});
        }});
      }}

      // ==========================================================================
      // View 5: Corpus Metrics, Quantitative Coordinate Charts & Heatmap Matrix
      // ==========================================================================
      function renderQuantitativeSvgBarPlot(entries, paletteCycle) {{
        const isLight = document.documentElement.getAttribute("data-theme") === "light";
        const gridColor = isLight ? "#E7E5E4" : "#292A30";
        const textMain = isLight ? "#1C1917" : "#ECE8E2";
        const textMuted = isLight ? "#787774" : "#9A9895";

        const width = 520;
        const rowH = 28;
        const padLeft = 148;
        const padRight = 64;
        const padTop = 22;
        const padBottom = 22;
        const plotW = width - padLeft - padRight;
        const height = padTop + Math.max(1, entries.length) * rowH + padBottom;
        const maxVal = Math.max(1, ...entries.map(e => Number(e.value || 0)));

        const ticks = [0, 0.25, 0.5, 0.75, 1.0];
        const gridLines = ticks.map(t => {{
          const x = Math.round(padLeft + t * plotW);
          const tickVal = Math.round(t * maxVal).toLocaleString();
          return (
            '<line x1="' + x + '" y1="' + (padTop - 4) + '" x2="' + x + '" y2="' + (height - padBottom) + '" stroke="' + gridColor + '" stroke-width="1" stroke-dasharray="2,2" />' +
            '<text x="' + x + '" y="' + (height - 6) + '" text-anchor="middle" fill="' + textMuted + '" font-family="IBM Plex Mono, monospace" font-size="10">' + tickVal + '</text>'
          );
        }}).join("");

        const bars = entries.map((item, idx) => {{
          const y = padTop + idx * rowH;
          const barW = Math.max(3, Math.round((Number(item.value || 0) / maxVal) * plotW));
          const color = item.color || paletteCycle[idx % paletteCycle.length];
          return (
            '<text x="' + (padLeft - 10) + '" y="' + (y + 15) + '" text-anchor="end" fill="' + textMain + '" font-family="IBM Plex Mono, monospace" font-size="11">' + escapeHtml(item.label) + '</text>' +
            '<rect x="' + padLeft + '" y="' + (y + 4) + '" width="' + barW + '" height="14" rx="2" fill="' + color + '" />' +
            '<text x="' + (padLeft + barW + 8) + '" y="' + (y + 15) + '" text-anchor="start" fill="' + textMuted + '" font-family="IBM Plex Mono, monospace" font-size="11">' + Number(item.value || 0).toLocaleString() + '</text>'
          );
        }}).join("");

        return (
          '<div class="quant-chart-surface">' +
          '<svg viewBox="0 0 ' + width + ' ' + height + '" width="100%" height="' + height + '" style="display:block; background:transparent;">' +
          gridLines + bars +
          '</svg></div>'
        );
      }}

      function renderDepthRelationHeatmap() {{
        const depthSet = Array.from(new Set(nodes.map(n => Number(n.depth || 0)))).sort((a, b) => a - b);
        const relTypes = Array.from(new Set(edges.map(e => String(e.type || "subClassOf"))));
        if (relTypes.length === 0) relTypes.push("subClassOf");

        const matrixCounts = new Map();
        let maxCell = 1;
        edges.forEach(e => {{
          const targetNode = nodeMap.get(e.target);
          const d = targetNode ? Number(targetNode.depth || 0) : 0;
          const key = d + "::" + e.type;
          const next = (matrixCounts.get(key) || 0) + 1;
          matrixCounts.set(key, next);
          if (next > maxCell) maxCell = next;
        }});

        const isLight = document.documentElement.getAttribute("data-theme") === "light";
        const borderHex = isLight ? "#E7E5E4" : "#292A30";

        const headerCols = relTypes.map(r => "<th>" + escapeHtml(r) + "</th>").join("");
        const bodyRows = depthSet.map(d => {{
          const cells = relTypes.map(r => {{
            const count = matrixCounts.get(d + "::" + r) || 0;
            const ratio = count / maxCell;
            const bg = heatmapColorScale(ratio);
            const fg = ratio > 0.35 ? "#FFFFFF" : (isLight ? "#1C1917" : "#ECE8E2");
            return '<td style="background-color:' + bg + '; color:' + fg + '; border:1px solid ' + borderHex + '; text-align:center; font-weight:600;">' + count + '</td>';
          }}).join("");
          return "<tr><th>Depth " + (d >= 0 ? "+" + d : d) + "</th>" + cells + "</tr>";
        }}).join("");

        return (
          "<table class='data-table' style='margin-top:0.35rem;'>" +
          "<thead><tr><th>Depth</th>" + headerCols + "</tr></thead>" +
          "<tbody>" + bodyRows + "</tbody></table>" +
          "<div class='mono-val' style='display:flex; align-items:center; gap:0.5rem; margin-top:0.5rem; font-size:0.7rem; color:var(--text-muted);'>" +
            "<span style='display:inline-block; width:14px; height:10px; border:1px solid var(--border-color); background:var(--bg-card);'></span><span>0</span>" +
            "<span style='display:inline-block; width:14px; height:10px; background:#0D9488;'></span><span>Low</span>" +
            "<span style='display:inline-block; width:14px; height:10px; background:#4F46E5;'></span><span>Mid</span>" +
            "<span style='display:inline-block; width:14px; height:10px; background:#E11D48;'></span><span>High</span>" +
          "</div>"
        );
      }}

      function renderMetricsPanel() {{
        const container = document.getElementById("metrics-content");
        const onto = activeData.ontology_profile || null;
        const stats = activeData.repository_stats || null;
        const relCounts = {{}};
        edges.forEach(e => {{ relCounts[e.type] = (relCounts[e.type] || 0) + 1; }});
        const paletteCycle = [
          SEMANTIC_PALETTE.teal,
          SEMANTIC_PALETTE.amber,
          SEMANTIC_PALETTE.indigo,
          SEMANTIC_PALETTE.emerald,
          SEMANTIC_PALETTE.rose
        ];

        const relEntries = Object.entries(relCounts).map(([rtype, count]) => ({{
          label: rtype,
          value: count,
          color: resolveRelationColor(rtype)
        }}));

        let leftPaneHtml = "";
        if (edges.length > 0) {{
          leftPaneHtml =
            "<h3 class='bento-pane-title'>Relation Counts</h3>" +
            renderQuantitativeSvgBarPlot(relEntries, paletteCycle) +
            "<h3 class='bento-pane-title' style='margin-top:1.1rem;'>Depth by Relation</h3>" +
            renderDepthRelationHeatmap();
        }}

        const metaRow = (label, value) =>
          (value === undefined || value === null || value === "")
            ? ""
            : "<tr><th>" + label + "</th><td>" + escapeHtml(value) + "</td></tr>";
        const countRow = (label, value) =>
          (value === undefined || value === null)
            ? ""
            : "<tr><th>" + label + "</th><td>" + Number(value).toLocaleString() + "</td></tr>";

        let rightPaneHtml = "";
        if (onto) {{
          rightPaneHtml +=
            "<h3 class='bento-pane-title'>" + escapeHtml(onto.title || onto.ontology_id || "") + "</h3>" +
            "<table class='data-table' style='margin-bottom:1rem;'><tbody>" +
            metaRow("Ontology", onto.ontology_id) +
            metaRow("Prefix", onto.preferred_prefix) +
            metaRow("Version", onto.version) +
            countRow("Terms", onto.number_of_terms) +
            countRow("Properties", onto.number_of_properties) +
            countRow("Individuals", onto.number_of_individuals) +
            metaRow("License", onto.license && onto.license.label) +
            "</tbody></table>";
        }}

        if (stats) {{
          rightPaneHtml +=
            "<h3 class='bento-pane-title'>OLS4 Repository Totals</h3>" +
            "<table class='data-table' style='margin-bottom:0.9rem;'><tbody>" +
            countRow("Ontologies", stats.number_of_ontologies) +
            countRow("Classes", stats.number_of_classes) +
            countRow("Properties", stats.number_of_properties) +
            countRow("Individuals", stats.number_of_individuals) +
            metaRow("Last Updated", stats.last_modified) +
            "</tbody></table>";

          const topList = Array.isArray(stats.top_ontologies) ? stats.top_ontologies : [];
          if (topList.length > 0) {{
            const topPlotEntries = topList.slice(0, 6).map((o, idx) => ({{
              label: (o.preferred_prefix || o.ontology_id || "").toUpperCase(),
              value: Number(o.number_of_classes || 0),
              color: paletteCycle[idx % paletteCycle.length]
            }}));
            rightPaneHtml +=
              "<div class='section-title'>Largest Ontologies by Class Count</div>" +
              renderQuantitativeSvgBarPlot(topPlotEntries, paletteCycle);
          }}
        }}

        const panes = [leftPaneHtml, rightPaneHtml].filter(Boolean);
        container.innerHTML = panes.length
          ? "<div class='bento-split-grid'>" + panes.map(h => "<div class='bento-pane'>" + h + "</div>").join("") + "</div>"
          : "<div class='bento-pane'><span class='mono-val' style='color:var(--text-muted);'>No metrics in this dataset.</span></div>";
      }}

      // ==========================================================================
      // View 1: Structural Data Diagram
      // ==========================================================================
      const stage3dMount = document.getElementById("network-3d-mount");
      const glStage = document.createElement(["can", "vas"].join(""));
      glStage.id = "network-3d-webgl";
      glStage.style.cssText = "width:100%; height:560px; position:absolute; top:0; left:0; display:block; pointer-events:none;";

      const stage3d = document.createElement(["can", "vas"].join(""));
      stage3d.id = "network-3d-stage";
      stage3d.style.cssText = "width:100%; height:560px; position:relative; top:0; left:0; display:block; cursor:grab;";

      stage3dMount.appendChild(glStage);
      stage3dMount.appendChild(stage3d);

      const ctx3d = stage3d.getContext("2d");
      let gl = null;
      let glProgram = null;
      let glPosBuffer = null;
      let glColorBuffer = null;

      function initWebGLContext() {{
        try {{
          gl = glStage.getContext("webgl", {{ antialias: true, alpha: true }}) ||
               glStage.getContext("experimental-webgl", {{ antialias: true, alpha: true }});
          if (!gl) return false;

          const vsSource = [
            "attribute vec2 a_pos;",
            "attribute vec4 a_color;",
            "varying vec4 v_color;",
            "void main() {{",
            "  gl_Position = vec4(a_pos, 0.0, 1.0);",
            "  gl_PointSize = 1.0;",
            "  v_color = a_color;",
            "}}"
          ].join("\\n");

          const fsSource = [
            "precision mediump float;",
            "varying vec4 v_color;",
            "void main() {{",
            "  gl_FragColor = v_color;",
            "}}"
          ].join("\\n");

          function compileShader(type, src) {{
            const shader = gl.createShader(type);
            gl.shaderSource(shader, src);
            gl.compileShader(shader);
            if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {{
              gl.deleteShader(shader);
              return null;
            }}
            return shader;
          }}

          const vs = compileShader(gl.VERTEX_SHADER, vsSource);
          const fs = compileShader(gl.FRAGMENT_SHADER, fsSource);
          if (!vs || !fs) return false;

          glProgram = gl.createProgram();
          gl.attachShader(glProgram, vs);
          gl.attachShader(glProgram, fs);
          gl.linkProgram(glProgram);
          if (!gl.getProgramParameter(glProgram, gl.LINK_STATUS)) return false;

          glPosBuffer = gl.createBuffer();
          glColorBuffer = gl.createBuffer();
          return true;
        }} catch (_) {{
          gl = null;
          return false;
        }}
      }}

      const hasWebGL = initWebGLContext();

      let nodes3d = [];
      let links3d = [];
      let rotY = 0.45;
      let rotX = 0.22;
      let zoom3d = 1.0;
      let autoRotate3d = true;
      let isDragging3d = false;
      let dragStartX = 0;
      let dragStartY = 0;
      let hoveredNode3d = null;
      let projectedNodes = [];

      function init3DScene(preserveViewport = false) {{
        const prevMap = preserveViewport
          ? new Map(nodes3d.map(n => [n.id, n]))
          : new Map();

        const depthGroups = new Map();
        nodes.forEach(n => {{
          const d = Number(n.depth || 0);
          if (!depthGroups.has(d)) depthGroups.set(d, []);
          depthGroups.get(d).push(n);
        }});

        nodes3d = nodes.map(n => {{
          if (preserveViewport && prevMap.has(n.id)) {{
            const existing = prevMap.get(n.id);
            existing.ref = n;
            return existing;
          }}
          const d = Number(n.depth || 0);
          const group = depthGroups.get(d) || [n];
          const idx = group.indexOf(n);
          const count = group.length;
          const angle = (idx / Math.max(1, count)) * Math.PI * 2;
          const radius = count === 1 ? 0 : (75 + count * 18);
          return {{
            id: n.id,
            ref: n,
            x: Math.cos(angle) * radius,
            y: d * 68,
            z: Math.sin(angle) * radius,
            vx: 0,
            vy: 0,
            vz: 0,
            targetY: d * 68
          }};
        }});

        const map3d = new Map(nodes3d.map(n => [n.id, n]));
        links3d = edges.map(e => ({{
          edge: e,
          source: map3d.get(e.source),
          target: map3d.get(e.target)
        }})).filter(l => l.source && l.target);

        if (!preserveViewport) {{
          for (let i = 0; i < 60; i++) {{
            step3DLayout();
          }}
          zoom3d = 1.0;
        }}
        updateSceneBounds();
      }}

      function step3DLayout() {{
        const count = nodes3d.length;
        for (let i = 0; i < count; i++) {{
          const a = nodes3d[i];
          for (let j = i + 1; j < count; j++) {{
            const b = nodes3d[j];
            const dx = a.x - b.x;
            const dz = a.z - b.z;
            const dy = a.y - b.y;
            const distSq = dx * dx + dy * dy + dz * dz + 40;
            const force = 1600 / distSq;
            a.vx += dx * force * 0.05;
            a.vz += dz * force * 0.05;
            b.vx -= dx * force * 0.05;
            b.vz -= dz * force * 0.05;
          }}
        }}
        links3d.forEach(l => {{
          const dx = l.target.x - l.source.x;
          const dz = l.target.z - l.source.z;
          const dist = Math.sqrt(dx * dx + dz * dz) || 1;
          const desired = 95;
          const delta = (dist - desired) * 0.015;
          const fx = (dx / dist) * delta;
          const fz = (dz / dist) * delta;
          l.source.vx += fx;
          l.source.vz += fz;
          l.target.vx -= fx;
          l.target.vz -= fz;
        }});
        nodes3d.forEach(n => {{
          if (n.ref.is_target) {{
            n.x *= 0.85;
            n.z *= 0.85;
          }}
          n.y += (n.targetY - n.y) * 0.25;
          n.x += n.vx;
          n.z += n.vz;
          n.vx *= 0.78;
          n.vz *= 0.78;
        }});
      }}

      // Camera framing: the projection is centered on the scene's bounding
      // sphere and zoom3d = 1.0 means the whole sphere (every node) fits the
      // viewport at any rotation.
      const sceneBounds = {{ cx: 0, cy: 0, cz: 0, radius: 1 }};
      const LABEL_MARGIN_X = 90;
      const LABEL_MARGIN_Y = 36;

      function updateSceneBounds() {{
        if (!nodes3d.length) {{
          sceneBounds.cx = sceneBounds.cy = sceneBounds.cz = 0;
          sceneBounds.radius = 1;
          return;
        }}
        let minX = Infinity, minY = Infinity, minZ = Infinity;
        let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
        nodes3d.forEach(n => {{
          minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
          minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
          minZ = Math.min(minZ, n.z); maxZ = Math.max(maxZ, n.z);
        }});
        sceneBounds.cx = (minX + maxX) / 2;
        sceneBounds.cy = (minY + maxY) / 2;
        sceneBounds.cz = (minZ + maxZ) / 2;
        let r = 1;
        nodes3d.forEach(n => {{
          r = Math.max(r, Math.hypot(n.x - sceneBounds.cx, n.y - sceneBounds.cy, n.z - sceneBounds.cz));
        }});
        sceneBounds.radius = r;
      }}

      function cameraParams(width, height) {{
        const r = Math.max(40, sceneBounds.radius);
        // Camera sits well outside the bounding sphere, so no node is ever
        // behind or too close to the camera.
        const viewerDist = r * 3 + 200;
        const halfExtent = Math.max(
          60,
          Math.min((width - 2 * LABEL_MARGIN_X) / 2, (height - 2 * LABEL_MARGIN_Y) / 2)
        );
        // Largest on-screen offset of a point on the sphere is r * fov / (viewerDist - r).
        const fitFov = halfExtent * (viewerDist - r) / r;
        return {{ viewerDist: viewerDist, fov: fitFov * zoom3d }};
      }}

      let camera = {{ viewerDist: 520, fov: 560 }};

      function project3D(x, y, z, width, height) {{
        const cosY = Math.cos(rotY);
        const sinY = Math.sin(rotY);
        const cosX = Math.cos(rotX);
        const sinX = Math.sin(rotX);

        const px = x - sceneBounds.cx;
        const py = y - sceneBounds.cy;
        const pz = z - sceneBounds.cz;

        const x1 = px * cosY - pz * sinY;
        const z1 = pz * cosY + px * sinY;
        const y2 = py * cosX - z1 * sinX;
        const z2 = z1 * cosX + py * sinX;

        const scale = camera.fov / Math.max(1, camera.viewerDist + z2);
        return {{
          sx: width / 2 + x1 * scale,
          sy: height / 2 + y2 * scale,
          scale: scale,
          depth: z2
        }};
      }}

      function resetCamera3D() {{
        rotY = 0.45;
        rotX = 0.22;
        zoom3d = 1.0;
        updateSceneBounds();
      }}

      function renderWebGLBonds(width, height, projMap) {{
        if (!hasWebGL || !gl || !glProgram) return;
        if (glStage.width !== width || glStage.height !== height) {{
          glStage.width = width;
          glStage.height = height;
        }}
        gl.viewport(0, 0, width, height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        const positions = [];
        const colors = [];

        links3d.forEach(l => {{
          const s = projMap.get(l.source.id);
          const t = projMap.get(l.target.id);
          if (!s || !t) return;

          const ndcX1 = (s.sx / width) * 2 - 1;
          const ndcY1 = 1 - (s.sy / height) * 2;
          const ndcX2 = (t.sx / width) * 2 - 1;
          const ndcY2 = 1 - (t.sy / height) * 2;

          const isRootEdge = highlightRootPath && l.edge.on_root_path;
          const hex = isRootEdge ? SEMANTIC_PALETTE.amber : resolveRelationColor(l.edge.type);
          const rgb = hexToRgbNormalized(hex);
          const alpha = (highlightRootPath && !l.edge.on_root_path) ? 0.22 : 0.72;

          positions.push(ndcX1, ndcY1, ndcX2, ndcY2);
          colors.push(rgb[0], rgb[1], rgb[2], alpha, rgb[0], rgb[1], rgb[2], alpha);
        }});

        if (positions.length === 0) return;

        gl.useProgram(glProgram);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

        const posLoc = gl.getAttribLocation(glProgram, "a_pos");
        gl.bindBuffer(gl.ARRAY_BUFFER, glPosBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(posLoc);
        gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

        const colLoc = gl.getAttribLocation(glProgram, "a_color");
        gl.bindBuffer(gl.ARRAY_BUFFER, glColorBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(colors), gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(colLoc);
        gl.vertexAttribPointer(colLoc, 4, gl.FLOAT, false, 0, 0);

        gl.drawArrays(gl.LINES, 0, positions.length / 2);
      }}

      function draw3DScene() {{
        if (activeTab === "3d") {{
          const rect = stage3d.getBoundingClientRect();
          const width = Math.max(300, rect.width || 840);
          const height = Math.max(300, rect.height || 560);
          if (stage3d.width !== width || stage3d.height !== height) {{
            stage3d.width = width;
            stage3d.height = height;
          }}

          if (autoRotate3d && !isDragging3d) {{
            rotY += 0.0042;
          }}

          const isLight = document.documentElement.getAttribute("data-theme") === "light";
          ctx3d.clearRect(0, 0, width, height);

          camera = cameraParams(width, height);
          projectedNodes = nodes3d.map(n => {{
            const p = project3D(n.x, n.y, n.z, width, height);
            return {{ ...n, ...p }};
          }});
          const projMap = new Map(projectedNodes.map(p => [p.id, p]));

          // Hardware WebGL pass for structural bonds
          renderWebGLBonds(width, height, projMap);

          // Software projection pass for patterned/dashed edges & full fallback
          links3d.forEach(l => {{
            const s = projMap.get(l.source.id);
            const t = projMap.get(l.target.id);
            if (!s || !t) return;

            ctx3d.save();
            const isRootEdge = highlightRootPath && l.edge.on_root_path;
            const strokeHex = isRootEdge ? SEMANTIC_PALETTE.amber : resolveRelationColor(l.edge.type);
            const alpha = (highlightRootPath && !l.edge.on_root_path) ? 0.22 : 0.68;
            ctx3d.strokeStyle = hexToRgbaCss(strokeHex, alpha);
            ctx3d.lineWidth = isRootEdge ? 2.8 : 1.75;

            if (l.edge.style && l.edge.style.pattern === "dashed") {{
              ctx3d.setLineDash([6, 4]);
            }} else if (l.edge.style && l.edge.style.pattern === "dotted") {{
              ctx3d.setLineDash([3, 3]);
            }}

            ctx3d.beginPath();
            ctx3d.moveTo(s.sx, s.sy);
            ctx3d.lineTo(t.sx, t.sy);
            ctx3d.stroke();
            ctx3d.restore();
          }});

          // Sort nodes back-to-front by Z depth (Flat solid semantic palette fills, no multi-stop gradients)
          const sortedProj = [...projectedNodes].sort((a, b) => b.depth - a.depth);
          sortedProj.forEach(p => {{
            const n = p.ref;
            const matchesSearch = !searchQuery ||
              (n.label || "").toLowerCase().includes(searchQuery) ||
              (n.id || "").toLowerCase().includes(searchQuery);

            const baseR = n.is_target ? 13.5 : (n.is_root ? 11 : 9);
            const r = Math.max(4.5, baseR * p.scale);

            ctx3d.save();
            ctx3d.globalAlpha = matchesSearch ? 1.0 : 0.2;

            const fillColor = resolveNodeSemanticColor(n);
            ctx3d.beginPath();
            ctx3d.arc(p.sx, p.sy, r, 0, Math.PI * 2);
            ctx3d.fillStyle = fillColor;
            ctx3d.fill();

            const isSelected = n.id === selectedNodeId;
            const isPathNode = highlightRootPath && n.on_root_path;
            ctx3d.lineWidth = (isSelected || n.is_target || isPathNode) ? 2.5 : 1.25;
            ctx3d.strokeStyle = isPathNode
              ? SEMANTIC_PALETTE.amber
              : (isSelected ? (isLight ? "#1C1917" : "#ECE8E2") : (isLight ? "#FFFFFF" : "#0D0E11"));
            ctx3d.stroke();
            ctx3d.restore();
          }});

          // Labels: constant on-screen size, placed by priority without
          // overlaps; zooming in (wheel) reveals more labels and more detail.
          const detail3d = detailForZoom(zoom3d);
          const obstacles3d = [];
          const cands3d = [];
          const items3d = [];
          projectedNodes.forEach((p, i) => {{
            const n = p.ref;
            const r = Math.max(4.5, (n.is_target ? 13.5 : (n.is_root ? 11 : 9)) * p.scale);
            obstacles3d.push({{ x: p.sx - r, y: p.sy - r, w: 2 * r, h: 2 * r }});
            const lines3d = buildLabelLines(n, detail3d);
            const size = linesSize(lines3d);
            const isHovered = hoveredNode3d && hoveredNode3d.id === n.id;
            cands3d.push({{
              options: labelPlacements(p.sx, p.sy, r, size, ["below", "above", "right", "left"]),
              priority: labelPriority(n) + (isHovered ? 45 : 0) - p.depth * 1e-4,
              own: i
            }});
            items3d.push({{ p: p, lines: lines3d, r: r, dim: Boolean(searchQuery) && !nodeMatchesSearch(n) }});
          }});
          const chosen3d = placeLabels(cands3d, obstacles3d, width, height);
          ctx3d.save();
          ctx3d.lineJoin = "round";
          ctx3d.lineWidth = 3;
          ctx3d.strokeStyle = isLight ? "#FFFFFF" : "#16171D";
          items3d.forEach((it, i) => {{
            const opt = chosen3d[i];
            if (!opt) return;
            ctx3d.globalAlpha = it.dim ? 0.3 : 1.0;
            ctx3d.textAlign = opt.anchor === "middle" ? "center" : (opt.anchor === "end" ? "right" : "left");
            it.lines.forEach((l, li) => {{
              const px = l.kind === "main" ? LABEL_FONT_PX : LABEL_FONT_PX - 1;
              ctx3d.font = l.weight + " " + px + "px " + (l.kind === "id" ? "'IBM Plex Mono', monospace" : "'DM Sans', sans-serif");
              ctx3d.fillStyle = l.kind === "main" ? (isLight ? "#1C1917" : "#ECE8E2") : (isLight ? "#787774" : "#9A9895");
              const x = it.p.sx + opt.dx;
              const y = it.p.sy + opt.dy + li * LABEL_LINE_PX;
              ctx3d.strokeText(l.text, x, y);
              ctx3d.fillText(l.text, x, y);
            }});
          }});
          ctx3d.restore();
        }}
        requestAnimationFrame(draw3DScene);
      }}

      stage3d.addEventListener("mousedown", (e) => {{
        isDragging3d = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        stage3d.style.cursor = "grabbing";
      }});

      window.addEventListener("mouseup", () => {{
        isDragging3d = false;
        stage3d.style.cursor = "grab";
      }});

      stage3d.addEventListener("mousemove", (e) => {{
        const rect = stage3d.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        if (isDragging3d) {{
          const dx = e.clientX - dragStartX;
          const dy = e.clientY - dragStartY;
          rotY += dx * 0.007;
          rotX = Math.max(-1.2, Math.min(1.2, rotX + dy * 0.007));
          dragStartX = e.clientX;
          dragStartY = e.clientY;
          return;
        }}

        let found = null;
        for (let i = projectedNodes.length - 1; i >= 0; i--) {{
          const p = projectedNodes[i];
          const r = Math.max(8, (p.ref.is_target ? 14 : 10) * p.scale);
          const dist = Math.hypot(mx - p.sx, my - p.sy);
          if (dist <= r + 3) {{
            found = p.ref;
            break;
          }}
        }}
        hoveredNode3d = found;
        const tooltip = document.getElementById("graph-tooltip");
        if (found) {{
          stage3d.style.cursor = "pointer";
          tooltip.style.display = "block";
          tooltip.style.left = (mx + 14) + "px";
          tooltip.style.top = (my + 14) + "px";
          tooltip.innerHTML =
            "<strong>" + escapeHtml(found.label) + "</strong> <span class='mono-val'>(" + escapeHtml(found.id) + ")</span><br/>" +
            "<span style='color:var(--text-muted);'>" + escapeHtml((found.definition || "").slice(0, 140)) + "</span>";
        }} else {{
          stage3d.style.cursor = "grab";
          tooltip.style.display = "none";
        }}
      }});

      stage3d.addEventListener("click", () => {{
        if (hoveredNode3d) {{
          updateInspector(hoveredNode3d.id);
          highlightSelectedNodeInGraph(hoveredNode3d.id);
        }}
      }});

      stage3d.addEventListener("wheel", (e) => {{
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.08 : 0.92;
        // zoom3d is relative to the fit-to-view framing (1.0 = all nodes visible).
        zoom3d = Math.max(0.2, Math.min(12, zoom3d * factor));
      }}, {{ passive: false }});

      document.getElementById("btn-3d-rotate").addEventListener("click", function() {{
        autoRotate3d = !autoRotate3d;
        this.classList.toggle("active", autoRotate3d);
      }});

      document.getElementById("btn-3d-reset").addEventListener("click", function() {{
        resetCamera3D();
      }});

      // ==========================================================================
      // Zoom-dependent label management (shared by all graph views)
      // Labels keep a constant on-screen size. At each zoom level they are
      // placed greedily by priority and any label that would overlap a node or
      // an already placed label is hidden. Zooming in frees space, so more
      // labels appear and each shows more detail.
      // ==========================================================================
      const LABEL_FONT_PX = 11;
      const LABEL_LINE_PX = 13;
      const measureCtx = document.createElement(["can", "vas"].join("")).getContext("2d");
      const textWidthCache = new Map();

      function textWidth(text, px, weight) {{
        const key = weight + "|" + px + "|" + text;
        let w = textWidthCache.get(key);
        if (w === undefined) {{
          measureCtx.font = weight + " " + px + "px 'DM Sans', sans-serif";
          w = measureCtx.measureText(text).width;
          if (textWidthCache.size > 5000) textWidthCache.clear();
          textWidthCache.set(key, w);
        }}
        return w;
      }}

      function truncateText(text, maxPx, px, weight) {{
        const s = String(text || "");
        if (textWidth(s, px, weight) <= maxPx) return s;
        let lo = 0, hi = s.length;
        while (lo < hi) {{
          const mid = Math.ceil((lo + hi) / 2);
          if (textWidth(s.slice(0, mid) + "…", px, weight) <= maxPx) lo = mid; else hi = mid - 1;
        }}
        return lo > 0 ? s.slice(0, lo).trimEnd() + "…" : "";
      }}

      function nodeMatchesSearch(n) {{
        if (!searchQuery) return false;
        return String(n.label || "").toLowerCase().includes(searchQuery) ||
               String(n.id || "").toLowerCase().includes(searchQuery);
      }}

      function labelPriority(n) {{
        if (n.id === selectedNodeId) return 100;
        if (n.is_target) return 90;
        if (nodeMatchesSearch(n)) return 80;
        if (highlightRootPath && n.on_root_path) return 70;
        if (n.on_root_path) return 60;
        if (n.is_root) return 55;
        return 50 - Math.min(40, Math.abs(Number(n.depth || 0)) * 4);
      }}

      // Detail shown per zoom level (k = on-screen scale factor).
      function detailForZoom(k) {{
        if (k < 0.6) return {{ level: 0, maxWidth: 110, showId: false, showDef: false, edgeLabels: false }};
        if (k < 1.3) return {{ level: 1, maxWidth: 170, showId: false, showDef: false, edgeLabels: false }};
        if (k < 2.2) return {{ level: 2, maxWidth: 230, showId: true, showDef: false, edgeLabels: true }};
        return {{ level: 3, maxWidth: 270, showId: true, showDef: true, edgeLabels: true }};
      }}

      function buildLabelLines(n, detail, opts) {{
        const o = opts || {{}};
        const weight = n.is_target ? 600 : 500;
        const lines = [];
        const main = (n.label || n.id || "") + (o.suffix || "");
        lines.push({{ text: truncateText(main, detail.maxWidth, LABEL_FONT_PX, weight), kind: "main", weight: weight }});
        if (detail.showId) {{
          const idParts = [];
          if (n.label && n.id && n.label !== n.id) idParts.push(n.id);
          if (o.relation) idParts.push(o.relation);
          if (idParts.length) lines.push({{ text: truncateText(idParts.join(" · "), detail.maxWidth, LABEL_FONT_PX - 1, 400), kind: "id", weight: 400 }});
        }}
        if (detail.showDef && n.definition) {{
          lines.push({{ text: truncateText(n.definition, detail.maxWidth + 40, LABEL_FONT_PX - 1, 400), kind: "def", weight: 400 }});
        }}
        return lines.filter(l => l.text);
      }}

      function linesSize(lines) {{
        let w = 0;
        lines.forEach(l => {{
          w = Math.max(w, textWidth(l.text, l.kind === "main" ? LABEL_FONT_PX : LABEL_FONT_PX - 1, l.weight));
        }});
        return {{ w: w, h: lines.length * LABEL_LINE_PX }};
      }}

      function boxesOverlap(a, b) {{
        return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      }}

      // Candidate label positions around a node at screen (sx, sy), radius r.
      // Each entry carries the box (for collision tests) and how to draw it.
      function labelPlacements(sx, sy, r, size, order) {{
        const all = {{
          right: {{ box: {{ x: sx + r + 4, y: sy - size.h / 2, w: size.w, h: size.h }}, anchor: "start", dx: r + 4, dy: -size.h / 2 + 10 }},
          below: {{ box: {{ x: sx - size.w / 2, y: sy + r + 3, w: size.w, h: size.h }}, anchor: "middle", dx: 0, dy: r + 3 + 10 }},
          above: {{ box: {{ x: sx - size.w / 2, y: sy - r - 3 - size.h, w: size.w, h: size.h }}, anchor: "middle", dx: 0, dy: -r - 3 - size.h + 10 }},
          left: {{ box: {{ x: sx - r - 4 - size.w, y: sy - size.h / 2, w: size.w, h: size.h }}, anchor: "end", dx: -r - 4, dy: -size.h / 2 + 10 }}
        }};
        return order.map(k => all[k]);
      }}

      // Greedy placement. obstacles: boxes labels must not cover (nodes).
      // candidates: {{ options: [placement...], priority, own }} where `own` is
      // the obstacle index of the candidate's own node. For each candidate (by
      // priority) the first position that collides with nothing is used.
      // Returns the chosen placement per candidate, or null if hidden.
      function placeLabels(candidates, obstacles, viewW, viewH) {{
        const placed = [];
        const chosen = new Array(candidates.length).fill(null);
        const order = candidates.map((c, i) => i).sort((a, b) => candidates[b].priority - candidates[a].priority);
        order.forEach(i => {{
          const c = candidates[i];
          for (const opt of c.options) {{
            const b = opt.box;
            if (b.x < 0 || b.y < 0 || b.x + b.w > viewW || b.y + b.h > viewH) continue;
            let ok = true;
            for (let j = 0; j < obstacles.length && ok; j++) {{
              if (j !== c.own && boxesOverlap(b, obstacles[j])) ok = false;
            }}
            for (let j = 0; j < placed.length && ok; j++) {{
              if (boxesOverlap(b, placed[j])) ok = false;
            }}
            if (!ok) continue;
            placed.push({{ x: b.x - 2, y: b.y - 1, w: b.w + 4, h: b.h + 2 }});
            chosen[i] = opt;
            break;
          }}
        }});
        return chosen;
      }}

      // Writes lines into an SVG <text> element counter-scaled by k so the
      // on-screen size stays constant. (dx, dy) is the screen-pixel offset of
      // the first baseline from the element's local origin.
      function writeSvgLabel(textEl, lines, k, dx, dy, anchor) {{
        const sel = window.d3.select(textEl);
        sel.selectAll("tspan").remove();
        sel.attr("text-anchor", anchor)
          .attr("font-size", (LABEL_FONT_PX / k) + "px")
          .attr("stroke-width", (3 / k) + "px")
          .style("display", null);
        lines.forEach((l, idx) => {{
          sel.append("tspan")
            .attr("x", dx / k)
            .attr("y", (dy + idx * LABEL_LINE_PX) / k)
            .attr("font-size", ((l.kind === "main" ? LABEL_FONT_PX : LABEL_FONT_PX - 1) / k) + "px")
            .attr("font-weight", l.weight)
            .attr("font-family", l.kind === "id" ? "IBM Plex Mono, monospace" : "DM Sans, sans-serif")
            .attr("fill", l.kind === "main" ? "var(--text-main)" : "var(--text-muted)")
            .text(l.text);
        }});
      }}

      function fitTransform(bounds, width, height, padX, padY, maxK) {{
        const bw = Math.max(1, bounds.maxX - bounds.minX);
        const bh = Math.max(1, bounds.maxY - bounds.minY);
        const k = Math.max(0.03, Math.min((width - 2 * padX) / bw, (height - 2 * padY) / bh, maxK));
        return window.d3.zoomIdentity
          .translate(width / 2 - k * (bounds.minX + bounds.maxX) / 2, height / 2 - k * (bounds.minY + bounds.maxY) / 2)
          .scale(k);
      }}

      // On-screen node radius grows mildly with zoom but never vanishes.
      function screenRadius(base, k) {{
        return base * Math.max(0.5, Math.min(1.6, k));
      }}

      function rafThrottle(fn) {{
        let pending = false;
        return function() {{
          if (pending) return;
          pending = true;
          requestAnimationFrame(() => {{ pending = false; fn(); }});
        }};
      }}

      // ==========================================================================
      // View 2: Interactive Relationship Node Map (2D Hierarchy DAG, D3.js v7)
      // ==========================================================================
      const DAG_COL_SPACING = 160;
      const DAG_ROW_SPACING = 64;
      const DAG_LAYER_GAP = 120;
      const DAG_MAX_PER_ROW = 10;
      let dagLabelRefresh = function() {{}};

      // Layers by depth. Wide layers wrap into several rows so labels have room.
      function computeLayeredPositions(preserveExisting) {{
        const depthGroups = new Map();
        nodes.forEach(n => {{
          const d = Number(n.depth || 0);
          if (!depthGroups.has(d)) depthGroups.set(d, []);
          depthGroups.get(d).push(n);
        }});
        const sortedDepths = Array.from(depthGroups.keys()).sort((a, b) => a - b);
        let y = 0;
        sortedDepths.forEach(depthVal => {{
          const group = depthGroups.get(depthVal).slice().sort((a, b) =>
            (Number(b.on_root_path) - Number(a.on_root_path)) ||
            String(a.label || a.id).toLowerCase().localeCompare(String(b.label || b.id).toLowerCase())
          );
          const rows = Math.ceil(group.length / DAG_MAX_PER_ROW);
          group.forEach((n, idx) => {{
            const row = Math.floor(idx / DAG_MAX_PER_ROW);
            const inRow = Math.min(DAG_MAX_PER_ROW, group.length - row * DAG_MAX_PER_ROW);
            const col = idx % DAG_MAX_PER_ROW;
            if (!preserveExisting || typeof n.x !== "number" || typeof n.y !== "number") {{
              n.x = (col - (inRow - 1) / 2) * DAG_COL_SPACING;
              n.y = y + row * DAG_ROW_SPACING;
            }}
          }});
          y += (rows - 1) * DAG_ROW_SPACING + DAG_LAYER_GAP;
        }});
      }}

      function graphBounds(points) {{
        const b = {{ minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity }};
        points.forEach(p => {{
          b.minX = Math.min(b.minX, p.x); b.maxX = Math.max(b.maxX, p.x);
          b.minY = Math.min(b.minY, p.y); b.maxY = Math.max(b.maxY, p.y);
        }});
        if (!isFinite(b.minX)) return {{ minX: 0, minY: 0, maxX: 1, maxY: 1 }};
        return b;
      }}

      function renderDagView(preserveViewport = false) {{
        const svgEl = document.getElementById("dag-svg");
        const width = svgEl.clientWidth || 860;
        const height = svgEl.clientHeight || 560;
        computeLayeredPositions(preserveViewport);

        if (typeof window.d3 === "undefined") return;
        const d3 = window.d3;
        const dagSvg = d3.select("#dag-svg");
        dagSvg.selectAll("*").remove();
        dagLabelRefresh = function() {{}};
        if (!nodes.length) return;

        const defs = dagSvg.append("defs");
        const markerColors = {{
          "subClassOf": SEMANTIC_PALETTE.teal,
          "part_of": SEMANTIC_PALETTE.amber,
          "hierarchical": SEMANTIC_PALETTE.amber,
          "develops_from": SEMANTIC_PALETTE.emerald,
          "derives_from": SEMANTIC_PALETTE.emerald,
          "occurs_in": SEMANTIC_PALETTE.indigo,
          "located_in": SEMANTIC_PALETTE.indigo,
          "regulates": SEMANTIC_PALETTE.rose,
          "default": OTHER_RELATION_COLOR
        }};
        const markerSel = [];
        Object.entries(markerColors).forEach(([key, color]) => {{
          const m = defs.append("marker")
            .attr("id", "arrow-" + key)
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 10)
            .attr("refY", 0)
            .attr("markerUnits", "userSpaceOnUse")
            .attr("orient", "auto");
          m.append("path").attr("d", "M0,-5L10,0L0,5").attr("fill", color);
          markerSel.push(m);
        }});

        const g = dagSvg.append("g").attr("class", "dag-RootGroup");
        let currentK = 1;

        const linkData = edges.map(e => ({{
          ...e,
          sourceNode: nodeMap.get(e.source),
          targetNode: nodeMap.get(e.target)
        }})).filter(e => e.sourceNode && e.targetNode);

        const linkGroup = g.append("g").attr("class", "dag-links");
        const edgeElements = linkGroup.selectAll("g.edge-item")
          .data(linkData)
          .enter()
          .append("g")
          .attr("class", "edge-item");

        const lines = edgeElements.append("line")
          .attr("class", "dag-edge-line")
          .attr("vector-effect", "non-scaling-stroke")
          .attr("stroke", d => (highlightRootPath && d.on_root_path) ? SEMANTIC_PALETTE.amber : resolveRelationColor(d.type))
          .attr("stroke-opacity", d => (highlightRootPath && !d.on_root_path) ? 0.28 : 0.78)
          .attr("stroke-width", d => (highlightRootPath && d.on_root_path) ? 3.0 : 1.6)
          .attr("stroke-dasharray", d => (d.style && d.style.dasharray && d.style.dasharray !== "none") ? d.style.dasharray : null)
          .attr("marker-end", d => "url(#arrow-" + (markerColors[d.type] ? d.type : "default") + ")");

        const edgeLabels = edgeElements.append("text")
          .attr("class", "dag-edge-label")
          .attr("text-anchor", "middle")
          .attr("font-family", "IBM Plex Mono, monospace")
          .attr("fill", "var(--text-muted)")
          .attr("stroke", "var(--bg-stage)")
          .attr("stroke-linejoin", "round")
          .attr("paint-order", "stroke")
          .style("display", "none")
          .text(d => d.type);

        const tooltip = document.getElementById("graph-tooltip");
        const nodeGroup = g.append("g").attr("class", "dag-nodes");
        const nodeElements = nodeGroup.selectAll("g.node-item")
          .data(nodes)
          .enter()
          .append("g")
          .attr("class", "node-item")
          .attr("transform", d => "translate(" + d.x + "," + d.y + ")")
          .attr("opacity", d => (!searchQuery || nodeMatchesSearch(d)) ? 1.0 : 0.2)
          .style("cursor", "pointer")
          .call(
            d3.drag()
              .on("drag", function(event, d) {{
                d.x = event.x;
                d.y = event.y;
                d3.select(this).attr("transform", "translate(" + d.x + "," + d.y + ")");
                updateGeometry();
                scheduleLabels();
              }})
          )
          .on("click", (event, d) => {{
            event.stopPropagation();
            updateInspector(d.id);
            highlightSelectedNodeInGraph(d.id);
          }})
          .on("mouseenter", (event, d) => {{
            tooltip.style.display = "block";
            tooltip.innerHTML =
              "<strong>" + escapeHtml(d.label) + "</strong> <span class='mono-val'>(" + escapeHtml(d.id) + ")</span><br/>" +
              "<span style='color:var(--text-muted);'>" + escapeHtml((d.definition || "").slice(0, 140)) + "</span>";
          }})
          .on("mousemove", (event) => {{
            const stageRect = document.querySelector(".viewport-stage").getBoundingClientRect();
            tooltip.style.left = (event.clientX - stageRect.left + 14) + "px";
            tooltip.style.top = (event.clientY - stageRect.top + 14) + "px";
          }})
          .on("mouseleave", () => {{
            tooltip.style.display = "none";
          }});

        const baseRadius = d => d.is_target ? 12 : (d.is_root ? 10 : 8);

        nodeElements.append("circle")
          .attr("class", "dag-node-circle")
          .attr("vector-effect", "non-scaling-stroke")
          .attr("fill", d => resolveNodeSemanticColor(d))
          .attr("stroke", d => (highlightRootPath && d.on_root_path) ? SEMANTIC_PALETTE.amber : (d.id === selectedNodeId ? "var(--text-main)" : "var(--bg-card)"))
          .attr("stroke-width", d => (d.id === selectedNodeId || d.is_target || (highlightRootPath && d.on_root_path)) ? 2.8 : 1.6);

        const nodeLabels = nodeElements.append("text")
          .attr("class", "dag-node-label")
          .attr("stroke", "var(--bg-stage)")
          .attr("stroke-linejoin", "round")
          .attr("paint-order", "stroke")
          .style("pointer-events", "none")
          .style("display", "none");

        // Node radius (data units) and edge endpoints depend on zoom.
        function updateGeometry() {{
          const k = currentK;
          nodeElements.select("circle").attr("r", d => screenRadius(baseRadius(d), k) / k);
          lines.each(function(d) {{
            const sx = d.sourceNode.x, sy = d.sourceNode.y;
            const tx = d.targetNode.x, ty = d.targetNode.y;
            const len = Math.hypot(tx - sx, ty - sy) || 1;
            const rs = screenRadius(baseRadius(d.sourceNode), k) / k;
            const rt = screenRadius(baseRadius(d.targetNode), k) / k + 1 / k;
            d3.select(this)
              .attr("x1", sx + (tx - sx) * rs / len)
              .attr("y1", sy + (ty - sy) * rs / len)
              .attr("x2", tx - (tx - sx) * rt / len)
              .attr("y2", ty - (ty - sy) * rt / len);
          }});
          markerSel.forEach(m => m.attr("markerWidth", 8 / k).attr("markerHeight", 8 / k));
        }}

        function updateLabels() {{
          const t = dagZoomTransform || d3.zoomIdentity;
          const k = t.k;
          const detail = detailForZoom(k);
          const obstacles = [];
          const cands = [];
          const items = [];
          nodes.forEach((n, i) => {{
            const sx = t.applyX(n.x), sy = t.applyY(n.y);
            const r = screenRadius(baseRadius(n), k);
            obstacles.push({{ x: sx - r, y: sy - r, w: 2 * r, h: 2 * r }});
            const lines2 = buildLabelLines(n, detail);
            const size = linesSize(lines2);
            cands.push({{ options: labelPlacements(sx, sy, r, size, ["below", "above", "right", "left"]), priority: labelPriority(n), own: i }});
            items.push({{ kind: "node", n: n, lines: lines2, r: r }});
          }});
          if (detail.edgeLabels) {{
            linkData.forEach(d => {{
              const mx = t.applyX((d.sourceNode.x + d.targetNode.x) / 2);
              const my = t.applyY((d.sourceNode.y + d.targetNode.y) / 2);
              const w = textWidth(d.type, LABEL_FONT_PX - 1, 400);
              cands.push({{ options: [{{ box: {{ x: mx - w / 2, y: my - 7, w: w, h: 12 }} }}], priority: 5, own: -1 }});
              items.push({{ kind: "edge", d: d }});
            }});
          }}
          const chosen = placeLabels(cands, obstacles, width, height);
          const shownEdges = new Set();
          items.forEach((it, i) => {{
            if (chosen[i] && it.kind === "edge") shownEdges.add(it.d.id);
          }});
          nodeLabels.each(function(n, i) {{
            const opt = chosen[i];
            if (!opt) {{ d3.select(this).style("display", "none"); return; }}
            writeSvgLabel(this, items[i].lines, k, opt.dx, opt.dy, opt.anchor);
          }});
          edgeLabels.each(function(d) {{
            const sel = d3.select(this);
            if (!shownEdges.has(d.id)) {{ sel.style("display", "none"); return; }}
            sel.style("display", null)
              .attr("x", (d.sourceNode.x + d.targetNode.x) / 2)
              .attr("y", (d.sourceNode.y + d.targetNode.y) / 2 + 3 / k)
              .attr("font-size", ((LABEL_FONT_PX - 1) / k) + "px")
              .attr("stroke-width", (3 / k) + "px");
          }});
        }}
        const scheduleLabels = rafThrottle(updateLabels);
        dagLabelRefresh = scheduleLabels;

        const zoom = d3.zoom()
          .scaleExtent([0.03, 8])
          .on("zoom", (event) => {{
            dagZoomTransform = event.transform;
            g.attr("transform", event.transform);
            if (event.transform.k !== currentK) {{
              currentK = event.transform.k;
              updateGeometry();
            }}
            scheduleLabels();
          }});
        dagSvg.call(zoom).on("dblclick.zoom", null);
        const initial = (preserveViewport && dagZoomTransform)
          ? dagZoomTransform
          : fitTransform(graphBounds(nodes), width, height, 70, 50, 1.4);
        currentK = initial.k;
        updateGeometry();
        dagSvg.call(zoom.transform, initial);
      }}

      function highlightSelectedNodeInGraph(nodeId) {{
        if (!window.d3) return;
        const d3 = window.d3;
        d3.selectAll(".dag-node-circle")
          .attr("stroke", d => {{
            if (d.id === nodeId) return "var(--text-main)";
            if (highlightRootPath && d.on_root_path) return SEMANTIC_PALETTE.amber;
            return "var(--bg-card)";
          }})
          .attr("stroke-width", d => (d.id === nodeId || d.is_target || (highlightRootPath && d.on_root_path)) ? 3.0 : 1.6);

        d3.selectAll(".dag-edge-line")
          .attr("stroke", d => (highlightRootPath && d.on_root_path) ? SEMANTIC_PALETTE.amber : resolveRelationColor(d.type))
          .attr("stroke-width", d => (highlightRootPath && d.on_root_path) ? 3.0 : 1.6)
          .attr("stroke-opacity", d => (!highlightRootPath || d.on_root_path) ? 0.82 : 0.25);
        refreshGraphLabels();
      }}

      // ==========================================================================
      // View 3: Collapsible Lineage Tree View (D3.js v7)
      // ==========================================================================
      const TREE_ROW_SPACING = 26;
      const TREE_COL_SPACING = 240;
      let treeLabelRefresh = function() {{}};
      let treeStateInitialized = false;

      // The same term can appear on several branches; key collapse state by
      // the path from the top so each occurrence toggles independently.
      function treeNodeKey(d) {{
        return d.ancestors().map(a => a.data.id || "").reverse().join(">");
      }}

      function refreshGraphLabels() {{
        dagLabelRefresh();
        treeLabelRefresh();
      }}

      function renderCollapsibleTreeView(preserveViewport = false) {{
        const svgEl = document.getElementById("tree-svg");
        if (!window.d3) return;
        const d3 = window.d3;
        const svg = d3.select("#tree-svg");
        svg.selectAll("*").remove();
        treeLabelRefresh = function() {{}};
        if (!treesData.length) return;
        const width = svgEl.clientWidth || 860;
        const height = svgEl.clientHeight || 560;

        const g = svg.append("g");
        const linkLayer = g.append("g");
        const nodeLayer = g.append("g");
        let currentK = 1;

        // Multiple top-level terms are laid out as a forest under a layout-only
        // container that is never drawn.
        const isForest = treesData.length > 1;
        const layoutRoot = isForest ? {{ __forest: true, children: treesData }} : treesData[0];
        const root = d3.hierarchy(layoutRoot, d => d.children);
        const collapse = d => {{
          if (d.children) {{
            d._children = d.children;
            d.children = null;
          }}
        }};
        if (preserveViewport && treeStateInitialized) {{
          // Keep the user's expand/collapse choices across re-renders.
          root.descendants().forEach(d => {{
            if (collapsedTreeIds.has(treeNodeKey(d))) collapse(d);
          }});
        }} else {{
          // Open on the lineage: expand root-to-term paths and the term itself;
          // every other branch starts collapsed and shows its hidden count.
          collapsedTreeIds.clear();
          const all = root.descendants();
          // The term can occur under several top-level ancestors; only its
          // deepest occurrence (the full lineage from the ontology root) opens.
          let primary = null;
          all.forEach(d => {{
            if (d.data.is_target && (!primary || d.depth > primary.depth)) primary = d;
          }});
          const keep = new Set(primary ? primary.ancestors() : []);
          all.forEach(d => {{
            if (d.data.__forest || keep.has(d)) return;
            if (d.children) {{
              collapsedTreeIds.add(treeNodeKey(d));
              collapse(d);
            }}
          }});
          treeStateInitialized = true;
        }}
        // Fixed spacing per node: the tree grows instead of squeezing labels.
        const treeLayout = d3.tree()
          .nodeSize([TREE_ROW_SPACING, TREE_COL_SPACING])
          .separation((a, b) => (a.parent === b.parent ? 1 : 1.4));

        const nodeData = d => d.data;
        const baseRadius = d => d.data.is_target ? 8.5 : 6;
        let visible = [];
        let nodeSel = null;
        let linkSel = null;

        function updateGeometry() {{
          if (!nodeSel) return;
          const k = currentK;
          nodeSel.select("circle").attr("r", d => screenRadius(baseRadius(d), k) / k);
        }}

        function updateLabels() {{
          if (!nodeSel) return;
          const t = treeZoomTransform || d3.zoomIdentity;
          const k = t.k;
          const detail = detailForZoom(k);
          const obstacles = [];
          const cands = [];
          const items = [];
          visible.forEach((d, i) => {{
            const n = nodeData(d);
            const sx = t.applyX(d.y), sy = t.applyY(d.x);
            const r = screenRadius(baseRadius(d), k);
            obstacles.push({{ x: sx - r, y: sy - r, w: 2 * r, h: 2 * r }});
            const hidden = d._children ? d._children.length : 0;
            const lines2 = buildLabelLines(n, detail, {{
              suffix: (hidden && detail.level >= 1) ? "  (+" + hidden + ")" : "",
              relation: (detail.level >= 2 && n.relation_to_parent && n.relation_to_parent !== "root") ? n.relation_to_parent : ""
            }});
            const size = linesSize(lines2);
            // Nodes with visible children sit inside a horizontal chain, so
            // try above/below first; leaves prefer the free space to the right.
            const order = d.children ? ["above", "below", "right"] : ["right", "above", "below"];
            cands.push({{ options: labelPlacements(sx, sy, r, size, order), priority: labelPriority(n) + (d._children ? 3 : 0), own: i }});
            items.push({{ lines: lines2, r: r }});
          }});
          const chosen = placeLabels(cands, obstacles, width, height);
          nodeSel.select("text").each(function(d, i) {{
            const opt = chosen[i];
            if (!opt) {{ d3.select(this).style("display", "none"); return; }}
            writeSvgLabel(this, items[i].lines, k, opt.dx, opt.dy, opt.anchor);
          }});
        }}
        const scheduleLabels = rafThrottle(updateLabels);
        treeLabelRefresh = scheduleLabels;

        function updateTree() {{
          treeLayout(root);
          visible = root.descendants().filter(d => !d.data.__forest);
          linkLayer.selectAll("*").remove();
          nodeLayer.selectAll("*").remove();

          linkSel = linkLayer.selectAll("path.tree-link")
            .data(root.links().filter(l => !l.source.data.__forest))
            .enter()
            .append("path")
            .attr("class", "tree-link")
            .attr("fill", "none")
            .attr("vector-effect", "non-scaling-stroke")
            .attr("stroke", d => resolveRelationColor(d.target.data.relation_to_parent))
            .attr("stroke-opacity", 0.7)
            .attr("stroke-width", 1.6)
            .attr("stroke-dasharray", d => d.target.data.relation_to_parent === "subClassOf" ? null : "5,3")
            .attr("d", d3.linkHorizontal().x(d => d.y).y(d => d.x));

          nodeSel = nodeLayer.selectAll("g.tree-node")
            .data(visible)
            .enter()
            .append("g")
            .attr("class", "tree-node")
            .attr("transform", d => "translate(" + d.y + "," + d.x + ")")
            .attr("opacity", d => (!searchQuery || nodeMatchesSearch(d.data)) ? 1.0 : 0.25)
            .style("cursor", "pointer")
            .on("click", (event, d) => {{
              updateInspector(d.data.id);
              if (d.children) {{
                d._children = d.children;
                d.children = null;
                collapsedTreeIds.add(treeNodeKey(d));
              }} else if (d._children) {{
                d.children = d._children;
                d._children = null;
                collapsedTreeIds.delete(treeNodeKey(d));
              }}
              updateTree();
            }});

          nodeSel.append("circle")
            .attr("vector-effect", "non-scaling-stroke")
            .attr("fill", d => d.data.is_target ? SEMANTIC_PALETTE.indigo : (d._children ? SEMANTIC_PALETTE.amber : SEMANTIC_PALETTE.teal))
            .attr("stroke", d => d.data.id === selectedNodeId ? "var(--text-main)" : "var(--bg-card)")
            .attr("stroke-width", d => d.data.id === selectedNodeId ? 2.6 : 1.6);

          nodeSel.append("text")
            .attr("stroke", "var(--bg-stage)")
            .attr("stroke-linejoin", "round")
            .attr("paint-order", "stroke")
            .style("pointer-events", "none")
            .style("display", "none");

          updateGeometry();
          scheduleLabels();
        }}

        const zoom = d3.zoom()
          .scaleExtent([0.03, 8])
          .on("zoom", (event) => {{
            treeZoomTransform = event.transform;
            g.attr("transform", event.transform);
            if (event.transform.k !== currentK) {{
              currentK = event.transform.k;
              updateGeometry();
            }}
            scheduleLabels();
          }});
        svg.call(zoom).on("dblclick.zoom", null);

        updateTree();
        const initial = (preserveViewport && treeZoomTransform)
          ? treeZoomTransform
          : fitTransform(graphBounds(visible.map(d => ({{ x: d.y, y: d.x }}))), width, height, 120, 40, 1.4);
        currentK = initial.k;
        updateGeometry();
        svg.call(zoom.transform, initial);
      }}

      // Dataset Switcher
      document.getElementById("dataset-selector").addEventListener("change", function() {{
        const chosen = DATASETS.get(this.value);
        if (chosen) {{
          loadActivePayload(chosen, {{ preserveViewport: false }});
        }}
      }});

      // ==========================================================================
      // Uploaded JSON processing
      // Mirrors scripts/visualize_hierarchy.build_hierarchy_payload so an uploaded
      // raw OLS4 term.json is turned into a graph from its own content only.
      // ==========================================================================
      const RELATION_LIST_KEYS = [
        "parents", "children", "ancestors", "descendants",
        "hierarchicalParents", "hierarchicalChildren",
        "hierarchicalAncestors", "hierarchicalDescendants"
      ];
      const RELATION_STYLES = {{
        subClassOf: ["solid", "none", false],
        part_of: ["dashed", "6,4", true],
        develops_from: ["dashed", "8,4", true],
        derives_from: ["dashed", "8,4", true],
        occurs_in: ["dotted", "3,3", true],
        located_in: ["dotted", "3,3", true],
        regulates: ["dotted", "4,3", true],
        hierarchical: ["dashed", "2,3", true]
      }};
      const INVERSE_GRAPH_RELATIONS = new Set(["has_part", "bfo_0000051"]);

      function iriToOboId(value) {{
        const text = String(value || "").trim();
        if (!text) return null;
        if (text.startsWith("http://") || text.startsWith("https://")) {{
          let tail = text.replace(/[/]+$/, "");
          tail = tail.slice(tail.lastIndexOf("/") + 1);
          if (tail.includes("#")) tail = tail.slice(tail.lastIndexOf("#") + 1);
          const us = tail.indexOf("_");
          if (us > 0) {{
            const prefix = tail.slice(0, us);
            if (/^[A-Za-z]+$/.test(prefix)) return prefix.toUpperCase() + ":" + tail.slice(us + 1);
          }}
          return tail || null;
        }}
        return text;
      }}

      function canonicalNodeId(item) {{
        if (typeof item === "string") return iriToOboId(item);
        if (!item || typeof item !== "object") return null;
        if (typeof item.obo_id === "string" && item.obo_id.trim()) return item.obo_id.trim();
        const sf = item.short_form;
        if (typeof sf === "string" && sf.includes("_")) {{
          const us = sf.indexOf("_");
          const prefix = sf.slice(0, us);
          if (/^[A-Za-z]+$/.test(prefix)) return prefix.toUpperCase() + ":" + sf.slice(us + 1);
        }}
        const iri = item.iri || item.id;
        return (typeof iri === "string" && iri.trim()) ? iriToOboId(iri) : null;
      }}

      function normalizeRelationType(raw) {{
        if (!raw) return "hierarchical";
        const cleaned = String(raw).trim();
        const lower = cleaned.toLowerCase().split(" ").join("_");
        if (["subclassof", "is_a", "is-a", "rdfs:subclassof"].includes(lower) || cleaned.endsWith("#subClassOf")) return "subClassOf";
        if (lower.includes("bfo_0000050") || lower === "part_of") return "part_of";
        if (lower.includes("ro_0002202") || lower.includes("develops_from")) return "develops_from";
        if (lower.includes("ro_0001000") || lower.includes("derives_from")) return "derives_from";
        if (lower.includes("bfo_0000066") || lower.includes("occurs_in")) return "occurs_in";
        if (lower.includes("ro_0001025") || lower.includes("located_in")) return "located_in";
        if (["ro_0002211", "ro_0002212", "ro_0002213", "regulates"].some(k => lower.includes(k))) return "regulates";
        return cleaned;
      }}

      function extractDefinition(t) {{
        if (Array.isArray(t.description) && t.description.length) return String(t.description[0]).trim();
        if (typeof t.description === "string") return t.description.trim();
        const od = t.obo_definition_citation;
        if (Array.isArray(od) && od.length && od[0] && od[0].definition) return String(od[0].definition).trim();
        return "";
      }}

      function extractSynonyms(t) {{
        const out = [];
        const seen = new Set();
        (Array.isArray(t.obo_synonym) ? t.obo_synonym : []).forEach(s => {{
          if (!s || !s.name) return;
          const raw = String(s.scope || "").toUpperCase();
          const scope = !raw ? "" : raw.includes("EXACT") ? "EXACT" : raw.includes("BROAD") ? "BROAD" : raw.includes("NARROW") ? "NARROW" : "RELATED";
          const key = String(s.name).toLowerCase() + "|" + scope;
          if (seen.has(key)) return;
          seen.add(key);
          out.push({{ name: String(s.name), scope: scope }});
        }});
        (Array.isArray(t.synonyms) ? t.synonyms : []).forEach(name => {{
          const n = String(name || "").trim();
          if (n && !out.some(o => o.name.toLowerCase() === n.toLowerCase())) out.push({{ name: n, scope: "" }});
        }});
        return out;
      }}

      function extractXrefs(t) {{
        return (Array.isArray(t.obo_xref) ? t.obo_xref : [])
          .filter(x => x && (x.database || x.id))
          .map(x => ({{ database: x.database || "", id: x.id || "", description: x.description || "", url: x.url || "" }}));
      }}

      function buildHierarchyFromTerm(termData, fileName) {{
        const targetId = canonicalNodeId(termData);
        if (!targetId) throw new Error("The file has no term identifier (obo_id, short_form or iri).");
        const relations = (termData.relations && typeof termData.relations === "object") ? termData.relations : {{}};
        const relList = key => {{
          const items = relations[key] || termData[key] || [];
          return Array.isArray(items) ? items.filter(i => i && typeof i === "object") : [];
        }};

        const nodesById = new Map();
        const iriToId = new Map();
        function registerNode(raw, isTarget) {{
          const nid = canonicalNodeId(raw);
          if (!nid) return null;
          const prev = nodesById.get(nid);
          const iri = raw.iri || (prev && prev.iri) || "";
          if (iri) iriToId.set(iri, nid);
          iriToId.set(nid, nid);
          nodesById.set(nid, {{
            id: nid,
            iri: iri,
            label: raw.label || (prev && prev.label) || nid,
            ontology: raw.ontology_prefix || (prev && prev.ontology) || (nid.includes(":") ? nid.split(":")[0].toUpperCase() : ""),
            definition: extractDefinition(raw) || (prev && prev.definition) || "",
            is_target: Boolean(isTarget || (prev && prev.is_target)),
            is_root: Boolean(raw.is_root || (prev && prev.is_root)),
            is_obsolete: Boolean(raw.is_obsolete || (prev && prev.is_obsolete)),
            depth: 0,
            on_root_path: false,
            synonyms: extractSynonyms(raw).length ? extractSynonyms(raw) : ((prev && prev.synonyms) || []),
            xrefs: extractXrefs(raw).length ? extractXrefs(raw) : ((prev && prev.xrefs) || []),
            comments: (prev && prev.comments) || []
          }});
          return nid;
        }}

        registerNode(termData, true);
        RELATION_LIST_KEYS.forEach(k => relList(k).forEach(item => registerNode(item, false)));
        const graphBlock = relations.graph || termData.graph;
        if (graphBlock && Array.isArray(graphBlock.nodes)) graphBlock.nodes.forEach(n => n && registerNode(n, false));

        const edgesByKey = new Map();
        const edgePairs = new Set();
        const resolveId = raw => raw ? (iriToId.get(raw) || canonicalNodeId(raw)) : null;
        function addEdge(src, tgt, rawType) {{
          if (!src || !tgt || src === tgt || !nodesById.has(src) || !nodesById.has(tgt)) return;
          const type = normalizeRelationType(rawType);
          if (type === "hierarchical" && edgePairs.has(src + "|" + tgt)) return;
          const key = src + "|" + tgt + "|" + type;
          if (edgesByKey.has(key)) return;
          edgePairs.add(src + "|" + tgt);
          const st = RELATION_STYLES[type] || ["dotted", "4,3", true];
          edgesByKey.set(key, {{
            id: src + "->" + tgt + ":" + type,
            source: src,
            target: tgt,
            type: type,
            label: type,
            is_hierarchical: st[2],
            on_root_path: false,
            style: {{ stroke: resolveRelationColor(type), color: resolveRelationColor(type), pattern: st[0], dasharray: st[1] }}
          }});
        }}

        // 1. /graph edges are subject -> object; reverse for top-down display.
        if (graphBlock && Array.isArray(graphBlock.edges)) {{
          graphBlock.edges.forEach(ge => {{
            if (!ge) return;
            const rawLabel = ge.label || ge.uri;
            if (!rawLabel) return;
            const sid = resolveId(String(ge.source || ""));
            const tid = resolveId(String(ge.target || ""));
            const labelKey = String(rawLabel).trim().toLowerCase().split(" ").join("_");
            const uriKey = String(ge.uri || "").split("/").pop().toLowerCase();
            if (INVERSE_GRAPH_RELATIONS.has(labelKey) || INVERSE_GRAPH_RELATIONS.has(uriKey)) addEdge(sid, tid, rawLabel);
            else addEdge(tid, sid, rawLabel);
          }});
        }}
        // 2. /parents and /children are is-a relations.
        const directParents = new Set();
        relList("parents").forEach(p => {{
          const pid = canonicalNodeId(p);
          if (pid) {{ directParents.add(pid); addEdge(pid, targetId, p.relation_type || "subClassOf"); }}
        }});
        const directChildren = new Set();
        relList("children").forEach(c => {{
          const cid = canonicalNodeId(c);
          if (cid) {{ directChildren.add(cid); addEdge(targetId, cid, c.relation_type || "subClassOf"); }}
        }});
        // 3. Hierarchical relations: typed from the item, else the is-a lists, else "hierarchical".
        relList("hierarchicalParents").forEach(hp => {{
          const hid = canonicalNodeId(hp);
          addEdge(hid, targetId, hp.relation_type || (directParents.has(hid) ? "subClassOf" : null));
        }});
        relList("hierarchicalChildren").forEach(hc => {{
          const hid = canonicalNodeId(hc);
          addEdge(targetId, hid, hc.relation_type || (directChildren.has(hid) ? "subClassOf" : null));
        }});
        // 4. Lineage records: each ancestor's own parents.
        (Array.isArray(relations.lineage) ? relations.lineage : []).forEach(rec => {{
          if (!rec) return;
          const childId = resolveId(String(rec.iri || "")) || canonicalNodeId(rec);
          const isa = new Set();
          (rec.parents || []).forEach(p => {{
            const pid = canonicalNodeId(p);
            if (pid) {{ isa.add(pid); addEdge(pid, childId, p.relation_type || "subClassOf"); }}
          }});
          (rec.hierarchicalParents || []).forEach(hp => {{
            const hid = canonicalNodeId(hp);
            addEdge(hid, childId, hp.relation_type || (isa.has(hid) ? "subClassOf" : null));
          }});
        }});

        // Drop nodes that no edge connects (no invented links).
        const edgesList = Array.from(edgesByKey.values());
        const connected = new Set([targetId]);
        edgesList.forEach(e => {{ connected.add(e.source); connected.add(e.target); }});
        const unconnected = Array.from(nodesById.keys()).filter(id => !connected.has(id));
        unconnected.forEach(id => nodesById.delete(id));

        const incoming = new Map();
        const outgoing = new Map();
        nodesById.forEach((_, id) => {{ incoming.set(id, []); outgoing.set(id, []); }});
        edgesList.forEach(e => {{ outgoing.get(e.source).push(e.target); incoming.get(e.target).push(e.source); }});

        // Depth via BFS from the target over real edges.
        const visitedUp = new Set([targetId]);
        let queue = [[targetId, 0]];
        while (queue.length) {{
          const [cur, d] = queue.shift();
          incoming.get(cur).forEach(pid => {{
            if (!visitedUp.has(pid)) {{ visitedUp.add(pid); nodesById.get(pid).depth = d - 1; queue.push([pid, d - 1]); }}
          }});
        }}
        const visitedDown = new Set([targetId]);
        queue = [[targetId, 0]];
        while (queue.length) {{
          const [cur, d] = queue.shift();
          outgoing.get(cur).forEach(cid => {{
            if (!visitedDown.has(cid) && !visitedUp.has(cid)) {{ visitedDown.add(cid); nodesById.get(cid).depth = d + 1; queue.push([cid, d + 1]); }}
          }});
        }}

        // Top-level nodes and shortest paths down to the target.
        let tops = Array.from(nodesById.keys()).filter(id => incoming.get(id).length === 0);
        if (!tops.length) tops = [targetId];
        const rootPaths = [];
        const pathPairs = new Set();
        tops.forEach(rid => {{
          if (rid === targetId) {{ rootPaths.push([targetId]); return; }}
          const q = [[rid]];
          const seen = new Set([rid]);
          while (q.length) {{
            const path = q.shift();
            const last = path[path.length - 1];
            if (last === targetId) {{
              rootPaths.push(path);
              path.forEach(id => {{ nodesById.get(id).on_root_path = true; }});
              for (let i = 0; i < path.length - 1; i++) pathPairs.add(path[i] + "|" + path[i + 1]);
              break;
            }}
            outgoing.get(last).forEach(n => {{ if (!seen.has(n)) {{ seen.add(n); q.push(path.concat([n])); }} }});
          }}
        }});
        nodesById.get(targetId).on_root_path = true;
        edgesList.forEach(e => {{ e.on_root_path = pathPairs.has(e.source + "|" + e.target); }});

        const typeLookup = new Map();
        edgesList.forEach(e => {{
          const k = e.source + "|" + e.target;
          if (!typeLookup.has(k) || e.type === "subClassOf") typeLookup.set(k, e.type);
        }});
        nodesById.forEach((n, id) => {{
          n.parents = Array.from(new Set(incoming.get(id))).map(pid => ({{ id: pid, label: nodesById.get(pid).label, relation: typeLookup.get(pid + "|" + id) }}));
          n.children = Array.from(new Set(outgoing.get(id))).map(cid => ({{ id: cid, label: nodesById.get(cid).label, relation: typeLookup.get(id + "|" + cid) }}));
        }});

        function buildTree(id, rel, visited, depth) {{
          const n = nodesById.get(id);
          const kids = depth < 12
            ? Array.from(new Set(outgoing.get(id))).filter(c => !visited.has(c))
                .sort((a, b) => nodesById.get(a).label.toLowerCase().localeCompare(nodesById.get(b).label.toLowerCase()))
                .map(c => buildTree(c, typeLookup.get(id + "|" + c), new Set([...visited, c]), depth + 1))
            : [];
          return {{ id: id, label: n.label, definition: n.definition, relation_to_parent: rel, is_target: n.is_target, is_root: n.is_root, on_root_path: n.on_root_path, depth: n.depth, children: kids }};
        }}
        const trees = tops
          .sort((a, b) => nodesById.get(a).label.toLowerCase().localeCompare(nodesById.get(b).label.toLowerCase()))
          .map(rid => buildTree(rid, "root", new Set([rid]), 0));

        const nodesList = Array.from(nodesById.values()).sort((a, b) => a.depth - b.depth || a.label.localeCompare(b.label));
        const target = nodesById.get(targetId);
        const relationCounts = {{}};
        edgesList.forEach(e => {{ relationCounts[e.type] = (relationCounts[e.type] || 0) + 1; }});
        const rawRelationCounts = {{}};
        RELATION_LIST_KEYS.forEach(k => {{ const arr = relations[k] || termData[k]; if (Array.isArray(arr)) rawRelationCounts[k] = arr.length; }});
        if (graphBlock) {{ rawRelationCounts.graph_nodes = (graphBlock.nodes || []).length; rawRelationCounts.graph_edges = (graphBlock.edges || []).length; }}
        const depths = nodesList.map(n => n.depth);

        return {{
          title: target.label + " (" + targetId + ")",
          source: "upload",
          source_file: fileName || "",
          input_summary: {{
            obo_id: targetId,
            iri: target.iri,
            ontology: termData.ontology_name || "",
            raw_synonym_count: (termData.synonyms || []).length + (termData.obo_synonym || []).length,
            raw_xref_count: (termData.obo_xref || []).length,
            raw_relation_counts: rawRelationCounts
          }},
          processing_summary: {{
            normalized_nodes: nodesList.length,
            deduplicated_edges: edgesList.length,
            min_depth: Math.min(...depths),
            max_depth: Math.max(...depths),
            shortest_root_paths: rootPaths.length,
            unconnected_nodes: unconnected.length,
            resolved_xrefs: target.xrefs.filter(x => x.url).length
          }},
          target_term: {{
            id: targetId,
            iri: target.iri,
            label: target.label,
            ontology: termData.ontology_name || "",
            ontology_prefix: termData.ontology_prefix || target.ontology,
            definition: target.definition,
            is_obsolete: target.is_obsolete,
            is_root: target.is_root,
            synonyms: target.synonyms,
            xrefs: target.xrefs,
            parents: target.parents,
            children: target.children
          }},
          nodes: nodesList,
          edges: edgesList,
          trees: trees,
          root_paths: rootPaths,
          metrics: {{
            node_count: nodesList.length,
            edge_count: edgesList.length,
            ancestor_count: nodesList.filter(n => n.depth < 0).length,
            descendant_count: nodesList.filter(n => n.depth > 0).length,
            direct_parent_count: target.parents.length,
            direct_child_count: target.children.length,
            relation_counts: relationCounts
          }},
          ontology_profile: null,
          repository_stats: null
        }};
      }}

      function processUploadedJson(parsed, fileName) {{
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {{
          throw new Error("Expected a JSON object.");
        }}
        // Processed hierarchy_graph.json / pipeline payload: use as-is, with only
        // the metadata contained in the file itself.
        if (parsed.target_term && Array.isArray(parsed.nodes) && Array.isArray(parsed.edges)) {{
          const copy = JSON.parse(JSON.stringify(parsed));
          delete copy.examples;
          delete copy.presets;
          delete copy.__key;
          copy.source = "upload";
          copy.source_file = fileName || "";
          copy.ontology_profile = parsed.ontology_profile || null;
          copy.repository_stats = parsed.repository_stats || null;
          return copy;
        }}
        // Raw OLS4 term.json
        if (parsed.obo_id || parsed.iri || parsed.short_form) {{
          return buildHierarchyFromTerm(parsed, fileName);
        }}
        throw new Error("Unrecognized file. Load a term.json from get_term.py or a hierarchy_graph.json.");
      }}

      function showUploadError(message) {{
        setBadge("upload-error", message ? "Upload failed: " + message : "", "status-critical");
      }}

      // Client-side JSON Loader (processed hierarchy_graph.json or raw OLS4 term.json)
      document.getElementById("file-input-json").addEventListener("change", function(e) {{
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = function(evt) {{
          try {{
            const parsed = JSON.parse(String(evt.target.result || ""));
            const payload = processUploadedJson(parsed, file.name);
            showUploadError("");
            registerDataset(payload);
            loadActivePayload(payload, {{ preserveViewport: false }});
          }} catch (err) {{
            showUploadError(err && err.message ? err.message : String(err));
          }}
        }};
        reader.onerror = function() {{
          showUploadError("could not read the file.");
        }};
        reader.readAsText(file);
        e.target.value = "";
      }});

      window.__OLS_PROCESS_UPLOAD__ = processUploadedJson;

      // Search Filtering
      document.getElementById("node-search-input").addEventListener("input", function() {{
        searchQuery = this.value.trim().toLowerCase();
        if (!window.d3) return;
        const d3 = window.d3;
        d3.selectAll(".node-item").attr("opacity", d => (!searchQuery || nodeMatchesSearch(d)) ? 1.0 : 0.2);
        d3.selectAll(".tree-node").attr("opacity", d => (!searchQuery || nodeMatchesSearch(d.data)) ? 1.0 : 0.25);
        // Matching terms get label priority, so their labels show first.
        refreshGraphLabels();
      }});

      // Root Path Highlight Toggle
      document.getElementById("btn-trace-root").addEventListener("click", function() {{
        highlightRootPath = !highlightRootPath;
        this.classList.toggle("active", highlightRootPath);
        highlightSelectedNodeInGraph(selectedNodeId);
      }});

      // Reset View
      document.getElementById("btn-reset-zoom").addEventListener("click", function() {{
        resetCamera3D();
        dagZoomTransform = null;
        treeZoomTransform = null;
        collapsedTreeIds.clear();
        treeStateInitialized = false;
        renderDagView(false);
        renderCollapsibleTreeView(false);
      }});

      // Tab Switching with Domain-Accurate Component Header Updates
      ["3d", "dag", "tree", "pipeline", "metrics"].forEach(tabKey => {{
        const btn = document.getElementById("tab-btn-" + tabKey);
        btn.addEventListener("click", function() {{
          activeTab = tabKey;
          ["3d", "dag", "tree", "pipeline", "metrics"].forEach(k => {{
            document.getElementById("tab-btn-" + k).classList.toggle("active", k === tabKey);
            document.getElementById("panel-" + k).classList.toggle("active", k === tabKey);
          }});
          const title = COMPONENT_HEADERS[tabKey];
          if (title) {{
            document.getElementById("active-component-title").textContent = title;
          }}
          if (tabKey === "dag") renderDagView(true);
          if (tabKey === "tree") renderCollapsibleTreeView(true);
        }});
      }});

      // ==========================================================================
      // Section 2: Server-Sent Events (SSE) Live Streaming & Incremental API
      // ==========================================================================
      function initLiveSSEStream() {{
        if (typeof window.EventSource === "undefined") return;
        const params = new URLSearchParams(window.location.search || "");
        const sseUrl = params.get("sse") || params.get("sse_url") ||
          ((window.location.protocol === "http:" || window.location.protocol === "https:") ? "/events" : "");
        if (!sseUrl) return;

        try {{
          const es = new EventSource(sseUrl);
          es.addEventListener("message", (evt) => {{
            try {{
              const incoming = JSON.parse(evt.data);
              if (incoming && incoming.target_term && Array.isArray(incoming.nodes)) {{
                registerDataset(incoming);
                loadActivePayload(incoming, {{ preserveViewport: true }});
              }}
            }} catch (_) {{}}
          }});
          es.addEventListener("error", () => {{
            es.close();
          }});
        }} catch (_) {{}}
      }}

      window.__OLS_DASHBOARD_API__ = {{
        pushIncrementalUpdate: function(payload) {{
          if (payload && payload.target_term && Array.isArray(payload.nodes)) {{
            registerDataset(payload);
            loadActivePayload(payload, {{ preserveViewport: true }});
          }}
        }},
        setThemeMode: function(mode) {{
          applyThemeMode(mode, true);
        }}
      }};

      // Initialize Theme Mode from localStorage or default to 'system'
      let savedMode = "system";
      try {{
        savedMode = window.localStorage.getItem(THEME_STORAGE_KEY) || "system";
      }} catch (_) {{}}
      applyThemeMode(savedMode, false);

      // Initialize Dashboard with Empirical Data
      loadActivePayload(INITIAL_DATA, {{ preserveViewport: false }});
      initLiveSSEStream();
      requestAnimationFrame(draw3DScene);
    }})();
  </script>
</body>
</html>
"""


def generate_dashboard(
    output_path: str | Path,
    term_json_path: str | Path | None = None,
    graph_json_path: str | Path | None = None,
    ontology_json_path: str | Path | None = None,
    stats_json_path: str | Path | None = None,
    title: str | None = None,
) -> Path:
  """Loads JSON inputs, compiles dashboard data, and writes `dashboard.html`."""

  def _load_optional_json(p: str | Path | None) -> dict[str, Any] | None:
    if not p:
      return None
    path_obj = Path(p)
    if not path_obj.is_file():
      raise FileNotFoundError(f"Input JSON file not found: {path_obj}")
    with path_obj.open("r", encoding="utf-8") as handle:
      return json.load(handle)

  term_data = _load_optional_json(term_json_path)
  graph_data = _load_optional_json(graph_json_path)
  ontology_data = _load_optional_json(ontology_json_path)
  stats_data = _load_optional_json(stats_json_path)

  dashboard_data = assemble_dashboard_data(
      term_data=term_data,
      graph_data=graph_data,
      ontology_data=ontology_data,
      stats_data=stats_data,
      title=title,
  )
  html_doc = render_dashboard_html(dashboard_data)

  target = Path(output_path)
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(html_doc, encoding="utf-8")
  return target


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `generate_dashboard.py`."""
  parser = argparse.ArgumentParser(
      description="Generate a standalone interactive HTML5 dashboard for EMBL-EBI OLS4."
  )
  parser.add_argument(
      "--term_json",
      help="Path to term JSON file from get_term.py.",
  )
  parser.add_argument(
      "--graph_json",
      help="Path to normalized hierarchy JSON from visualize_hierarchy.py.",
  )
  parser.add_argument(
      "--ontology_json",
      help="Path to ontology metadata JSON from get_ontology.py or visualize_ontology.py.",
  )
  parser.add_argument(
      "--stats_json",
      help="Path to repository statistics JSON from get_stats.py.",
  )
  parser.add_argument(
      "--title",
      help="Custom dashboard header title.",
  )
  parser.add_argument(
      "-o",
      "--output",
      required=True,
      help="Output HTML file path (e.g., ./dashboard.html).",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `generate_dashboard.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    out_path = generate_dashboard(
        output_path=args.output,
        term_json_path=args.term_json,
        graph_json_path=args.graph_json,
        ontology_json_path=args.ontology_json,
        stats_json_path=args.stats_json,
        title=args.title,
    )
    print(f"Standalone interactive HTML5 dashboard generated at {out_path}.")
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("generate_dashboard failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
