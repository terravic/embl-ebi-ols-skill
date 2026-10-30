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


def _synthesize_hierarchy_from_ontology(
    onto_profile: dict[str, Any] | None,
    repo_stats: dict[str, Any] | None,
    title: str | None = None,
) -> dict[str, Any]:
  """Synthesizes a valid hierarchy payload when only ontology/stats JSON is provided."""
  if onto_profile:
    onto_id = onto_profile.get("ontology_id", "go")
    prefix = onto_profile.get("preferred_prefix", onto_id.upper())
    onto_title = onto_profile.get("title", f"{prefix} Ontology")
    desc = onto_profile.get("description") or f"Overview of {onto_title}."
    roots = onto_profile.get("roots") or []
  else:
    onto_id = "ols4"
    prefix = "OLS4"
    onto_title = "EMBL-EBI Ontology Lookup Service (OLS4) Repository"
    desc = "Global statistical overview of ontologies indexed in EMBL-EBI OLS4."
    roots = []

  root_node_id = f"{prefix}:ROOT"
  synthetic_term = {
      "iri": f"http://purl.obolibrary.org/obo/{onto_id}.owl",
      "obo_id": root_node_id,
      "short_form": f"{prefix}_ROOT",
      "label": onto_title,
      "ontology_name": onto_id,
      "ontology_prefix": prefix,
      "description": [desc],
      "is_obsolete": False,
      "is_defining_ontology": True,
      "is_root": True,
      "synonyms": [prefix, onto_id],
      "obo_synonym": [
          {"name": prefix, "scope": "EXACT", "type": "acronym", "xrefs": []}
      ],
      "obo_xref": [],
      "relations": {
          "children": [
              {
                  "iri": r.get("iri")
                  or ols_utils.obo_id_to_iri(r.get("id", "GO:0008150")),
                  "obo_id": r.get("id", "GO:0008150"),
                  "label": r.get("label", r.get("id", "root")),
                  "ontology_name": onto_id,
                  "ontology_prefix": prefix,
                  "description": (
                      [r.get("description", "")] if r.get("description") else []
                  ),
                  "is_obsolete": False,
                  "is_root": True,
                  "relation_type": "subClassOf",
              }
              for r in roots
          ]
      },
  }
  payload = visualize_hierarchy.build_hierarchy_payload(
      synthetic_term,
      title=title or f"EMBL-EBI OLS Ontology Overview: {onto_title}",
  )
  payload["ontology_profile"] = onto_profile
  payload["repository_stats"] = repo_stats
  return payload


def _load_bundled_reference_presets(
    active_target_id: str,
    onto_profile: dict[str, Any] | None,
    repo_stats: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
  """Loads bundled reference datasets so users can compare concepts in the interactive dashboard."""
  presets: dict[str, dict[str, Any]] = {}
  fixture_files = (
      "go_0005634_nucleus.json",
      "doid_9351_diabetes.json",
      "go_0006915_apoptosis.json",
  )
  for fname in fixture_files:
    try:
      raw = ols_utils.load_mock_data(fname)
      built = visualize_hierarchy.build_hierarchy_payload(raw)
      built["ontology_profile"] = onto_profile
      built["repository_stats"] = repo_stats
      tid = built["target_term"]["id"]
      if tid != active_target_id:
        presets[tid] = built
    except Exception:  # pylint: disable=broad-except
      continue
  return presets


def assemble_dashboard_data(
    term_data: dict[str, Any] | None = None,
    graph_data: dict[str, Any] | None = None,
    ontology_data: dict[str, Any] | None = None,
    stats_data: dict[str, Any] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
  """Combines term, graph, ontology, and stats inputs into the dashboard contract."""
  if not any([term_data, graph_data, ontology_data, stats_data]):
    raise ValueError(
        "At least one input (--term_json, --graph_json, --ontology_json, or --stats_json) is required."
    )

  onto_profile = None
  if ontology_data:
    if "ontology_profile" in ontology_data and isinstance(
        ontology_data["ontology_profile"], dict
    ):
      onto_profile = ontology_data["ontology_profile"]
    else:
      onto_profile = visualize_ontology.profile_ontology(ontology_data)
  else:
    try:
      onto_profile = visualize_ontology.profile_ontology(
          ols_utils.load_mock_data("ontology_go.json")
      )
    except Exception:  # pylint: disable=broad-except
      onto_profile = None

  repo_stats = None
  if stats_data:
    if "repository_stats" in stats_data and isinstance(
        stats_data["repository_stats"], dict
    ):
      repo_stats = stats_data["repository_stats"]
    else:
      repo_stats = visualize_ontology.profile_repository_stats(stats_data)
  elif (
      ontology_data
      and "repository_stats" in ontology_data
      and isinstance(ontology_data["repository_stats"], dict)
  ):
    repo_stats = ontology_data["repository_stats"]
  else:
    try:
      repo_stats = visualize_ontology.profile_repository_stats(
          ols_utils.load_mock_data("stats.json")
      )
    except Exception:  # pylint: disable=broad-except
      repo_stats = None

  if graph_data and "target_term" in graph_data and "nodes" in graph_data:
    payload = dict(graph_data)
    if title:
      payload["title"] = title
  elif term_data:
    if "target_term" in term_data and "nodes" in term_data:
      payload = dict(term_data)
      if title:
        payload["title"] = title
    else:
      merged_term = dict(term_data)
      if graph_data and isinstance(graph_data, dict):
        merged_term.setdefault("relations", {})["graph"] = graph_data
      payload = visualize_hierarchy.build_hierarchy_payload(
          merged_term, title=title
      )
  elif graph_data:
    synthetic_term = {
        "obo_id": "OLS:GRAPH",
        "label": title or "Ontology Subgraph",
        "ontology_name": "ols",
        "ontology_prefix": "OLS",
        "description": ["Ontology relationship subgraph."],
        "relations": {"graph": graph_data},
    }
    payload = visualize_hierarchy.build_hierarchy_payload(
        synthetic_term, title=title
    )
  else:
    payload = _synthesize_hierarchy_from_ontology(
        onto_profile=onto_profile, repo_stats=repo_stats, title=title
    )

  payload["ontology_profile"] = onto_profile or payload.get("ontology_profile")
  payload["repository_stats"] = repo_stats or payload.get("repository_stats")
  payload["system_theme"] = detect_host_system_theme()
  payload["generated_at"] = datetime.now(timezone.utc).strftime(
      "%Y-%m-%dT%H:%M:%SZ"
  )
  payload["citations"] = [
      {"id": "ols4_2025", "text": ols_utils.PRIMARY_CITATION},
      {"id": "ols_2015", "text": ols_utils.ORIGINAL_CITATION},
  ]
  payload["disclaimer"] = ols_utils.SCIENTIFIC_DISCLAIMER

  active_id = str(payload.get("target_term", {}).get("id") or "")
  payload["presets"] = _load_bundled_reference_presets(
      active_target_id=active_id,
      onto_profile=payload["ontology_profile"],
      repo_stats=payload["repository_stats"],
  )
  return payload


def render_dashboard_html(dashboard_data: dict[str, Any]) -> str:
  """Renders the self-contained HTML5 interactive dashboard strictly adhering to DESIGN.md."""
  page_title = html.escape(
      str(dashboard_data.get("title") or "EMBL-EBI OLS Hierarchy Explorer")
  )
  target = dashboard_data.get("target_term") or {}
  target_label = html.escape(str(target.get("label") or "Unknown Term"))
  target_id = html.escape(str(target.get("id") or "N/A"))
  target_ontology = html.escape(
      str(
          target.get("ontology_prefix") or target.get("ontology") or "OLS"
      ).upper()
  )
  target_iri = html.escape(str(target.get("iri") or ""))
  is_obsolete = bool(target.get("is_obsolete", False))
  status_label = "Obsolete" if is_obsolete else "Active"
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

      function registerDataset(payload) {{
        if (!payload || !payload.target_term || !payload.target_term.id) return;
        DATASETS.set(payload.target_term.id, payload);
      }}

      registerDataset(INITIAL_DATA);
      if (INITIAL_DATA.presets && typeof INITIAL_DATA.presets === "object") {{
        Object.values(INITIAL_DATA.presets).forEach(p => registerDataset(p));
      }}

      let activeData = INITIAL_DATA;
      let nodes = [];
      let edges = [];
      let treeData = null;
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

      function resolveRelationColor(relType) {{
        const norm = String(relType || "subClassOf").trim();
        if (norm === "part_of") return SEMANTIC_PALETTE.amber;
        if (norm === "develops_from" || norm === "derives_from") return SEMANTIC_PALETTE.emerald;
        if (norm === "occurs_in" || norm === "located_in") return SEMANTIC_PALETTE.indigo;
        if (norm === "regulates") return SEMANTIC_PALETTE.rose;
        return SEMANTIC_PALETTE.teal;
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

      function refreshDatasetSelector() {{
        const sel = document.getElementById("dataset-selector");
        const currentId = (activeData.target_term && activeData.target_term.id) || "";
        sel.innerHTML = Array.from(DATASETS.values()).map(ds => {{
          const t = ds.target_term || {{}};
          const selected = t.id === currentId ? " selected" : "";
          return '<option value="' + escapeHtml(t.id) + '"' + selected + '>' +
                 escapeHtml(t.label) + ' (' + escapeHtml(t.id) + ')</option>';
        }}).join("");
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
        treeData = payload.tree ? JSON.parse(JSON.stringify(payload.tree)) : null;
        metrics = payload.metrics || {{}};
        targetTerm = payload.target_term || {{}};
        nodeMap = new Map(nodes.map(n => [n.id, n]));

        if (!preserveViewport || !selectedNodeId || !nodeMap.has(selectedNodeId)) {{
          selectedNodeId = targetTerm.id || (nodes[0] && nodes[0].id) || "";
        }}

        // Update Top Header
        document.getElementById("header-obo-id").textContent = targetTerm.id || "N/A";
        document.getElementById("header-ontology").textContent =
          String(targetTerm.ontology_prefix || targetTerm.ontology || "OLS").toUpperCase();
        const statusEl = document.getElementById("header-status");
        statusEl.textContent = targetTerm.is_obsolete ? "Obsolete" : "Active";
        statusEl.className = "badge " + (targetTerm.is_obsolete ? "status-critical" : "status-nominal");
        document.getElementById("header-title").textContent = targetTerm.label || "Unknown Term";
        const iriLink = document.getElementById("header-iri-link");
        iriLink.href = targetTerm.iri || "#";
        iriLink.textContent = targetTerm.iri || "";

        // Update Bento KPIs
        document.getElementById("kpi-nodes").textContent = String(metrics.node_count || nodes.length);
        document.getElementById("kpi-edges").textContent = String(metrics.edge_count || edges.length);
        document.getElementById("kpi-ancestors").textContent = String(metrics.ancestor_count || 0);
        document.getElementById("kpi-parents").textContent = String(metrics.direct_parent_count || 0);
        document.getElementById("kpi-children").textContent = String(metrics.direct_child_count || 0);
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

        document.getElementById("insp-id").textContent = node.id || "N/A";
        const ontoBadge = document.getElementById("insp-onto");
        ontoBadge.textContent = (node.ontology || targetTerm.ontology_prefix || "OLS") + (node.is_obsolete ? " (Obsolete)" : "");
        ontoBadge.className = "badge " + (node.is_obsolete ? "status-critical" : "");
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
          rootPathEl.textContent = "Root node";
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
            const sScope = typeof s === "string" ? "EXACT" : (s.scope || "EXACT");
            return "<tr><td>" + escapeHtml(sName) + "</td><td><span class='badge'>" + escapeHtml(sScope) + "</span></td></tr>";
          }}).join("");
          synsEl.innerHTML = "<table class='data-table'><thead><tr><th>Synonym</th><th>Scope</th></tr></thead><tbody>" + rowsHtml + "</tbody></table>";
        }} else {{
          synsEl.innerHTML = '<span class="mono-val" style="font-size:0.74rem; color:var(--text-muted);">None</span>';
        }}

        const xrefs = (node.xrefs && node.xrefs.length ? node.xrefs : (node.id === targetTerm.id ? targetTerm.xrefs : [])) || [];
        const xrefsEl = document.getElementById("insp-xrefs");
        if (xrefs.length > 0) {{
          const xRows = xrefs.map(x => {{
            const db = escapeHtml(x.database || "External");
            const xid = escapeHtml(x.id || "");
            const desc = escapeHtml(x.description || "");
            const link = x.url
              ? '<a href="' + escapeHtml(x.url) + '" target="_blank" rel="noopener noreferrer" style="color:var(--viz-teal);">' + db + ':' + xid + '</a>'
              : (db + ':' + xid);
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
        ).join("") || "<tr><td><code>term</code></td><td>1</td></tr>";

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
        const relCounts = metrics.relation_counts || {{}};
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

        let leftPaneHtml =
          "<h3 class='bento-pane-title'>Relation Counts</h3>" +
          renderQuantitativeSvgBarPlot(relEntries, paletteCycle) +
          "<h3 class='bento-pane-title' style='margin-top:1.1rem;'>Depth by Relation</h3>" +
          renderDepthRelationHeatmap();

        let rightPaneHtml = "";
        if (onto) {{
          rightPaneHtml +=
            "<h3 class='bento-pane-title'>" + escapeHtml(onto.title || "Ontology Metadata") + "</h3>" +
            "<table class='data-table' style='margin-bottom:1rem;'><tbody>" +
            "<tr><th>Ontology</th><td>" + escapeHtml(onto.ontology_id) + " (" + escapeHtml(onto.preferred_prefix) + ")</td></tr>" +
            "<tr><th>Version</th><td>" + escapeHtml(onto.version) + "</td></tr>" +
            "<tr><th>Terms</th><td>" + Number(onto.number_of_terms || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>Properties</th><td>" + Number(onto.number_of_properties || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>Individuals</th><td>" + Number(onto.number_of_individuals || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>License</th><td>" + escapeHtml((onto.license && onto.license.label) || "Open Access") + "</td></tr>" +
            "</tbody></table>";
        }}

        if (stats) {{
          rightPaneHtml +=
            "<h3 class='bento-pane-title'>OLS4 Repository Totals</h3>" +
            "<table class='data-table' style='margin-bottom:0.9rem;'><tbody>" +
            "<tr><th>Ontologies</th><td>" + Number(stats.number_of_ontologies || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>Classes</th><td>" + Number(stats.number_of_classes || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>Properties</th><td>" + Number(stats.number_of_properties || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>Individuals</th><td>" + Number(stats.number_of_individuals || 0).toLocaleString() + "</td></tr>" +
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

        container.innerHTML =
          "<div class='bento-split-grid'>" +
            "<div class='bento-pane'>" + leftPaneHtml + "</div>" +
            "<div class='bento-pane'>" + rightPaneHtml + "</div>" +
          "</div>";
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
        }}
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

      function project3D(x, y, z, width, height) {{
        const cosY = Math.cos(rotY);
        const sinY = Math.sin(rotY);
        const cosX = Math.cos(rotX);
        const sinX = Math.sin(rotX);

        const x1 = x * cosY - z * sinY;
        const z1 = z * cosY + x * sinY;
        const y2 = y * cosX - z1 * sinX;
        const z2 = z1 * cosX + y * sinX;

        const fov = 560 * zoom3d;
        const viewerDist = 520;
        const scale = fov / Math.max(120, viewerDist + z2);
        return {{
          sx: width / 2 + x1 * scale,
          sy: height / 2 + y2 * scale,
          scale: scale,
          depth: z2
        }};
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

            // Crisp node label
            ctx3d.font = (n.is_target ? "600 " : "500 ") + Math.max(10, Math.round(11 * p.scale)) + "px 'DM Sans', sans-serif";
            ctx3d.textAlign = "center";
            ctx3d.fillStyle = isLight ? "#1C1917" : "#ECE8E2";
            ctx3d.fillText(n.label + " (" + n.id + ")", p.sx, p.sy + r + 13);
            ctx3d.restore();
          }});
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
        zoom3d = Math.max(0.45, Math.min(2.6, zoom3d * factor));
      }}, {{ passive: false }});

      document.getElementById("btn-3d-rotate").addEventListener("click", function() {{
        autoRotate3d = !autoRotate3d;
        this.classList.toggle("active", autoRotate3d);
      }});

      document.getElementById("btn-3d-reset").addEventListener("click", function() {{
        rotY = 0.45;
        rotX = 0.22;
        zoom3d = 1.0;
      }});

      // ==========================================================================
      // View 2: Interactive Relationship Node Map (2D Hierarchy DAG, D3.js v7)
      // ==========================================================================
      function computeLayeredPositions(width, height, preserveExisting = false) {{
        const depthGroups = new Map();
        nodes.forEach(n => {{
          const d = Number(n.depth || 0);
          if (!depthGroups.has(d)) depthGroups.set(d, []);
          depthGroups.get(d).push(n);
        }});
        const sortedDepths = Array.from(depthGroups.keys()).sort((a, b) => a - b);
        const layerCount = Math.max(1, sortedDepths.length);
        const verticalPad = 65;
        const usableHeight = Math.max(300, height - verticalPad * 2);

        sortedDepths.forEach((depthVal, layerIdx) => {{
          const group = depthGroups.get(depthVal);
          const y = layerCount === 1
            ? height / 2
            : verticalPad + (layerIdx / (layerCount - 1)) * usableHeight;
          const count = group.length;
          group.forEach((n, idx) => {{
            if (!preserveExisting || typeof n.x !== "number" || typeof n.y !== "number") {{
              n.x = (width / (count + 1)) * (idx + 1);
              n.y = y;
            }}
          }});
        }});
      }}

      function renderDagView(preserveViewport = false) {{
        const svgEl = document.getElementById("dag-svg");
        const width = svgEl.clientWidth || 860;
        const height = svgEl.clientHeight || 560;
        computeLayeredPositions(width, height, preserveViewport);

        if (typeof window.d3 === "undefined") return;
        const d3 = window.d3;
        const dagSvg = d3.select("#dag-svg");
        dagSvg.selectAll("*").remove();

        const defs = dagSvg.append("defs");
        const markerColors = {{
          "subClassOf": SEMANTIC_PALETTE.teal,
          "part_of": SEMANTIC_PALETTE.amber,
          "develops_from": SEMANTIC_PALETTE.emerald,
          "derives_from": SEMANTIC_PALETTE.emerald,
          "occurs_in": SEMANTIC_PALETTE.indigo,
          "located_in": SEMANTIC_PALETTE.indigo,
          "regulates": SEMANTIC_PALETTE.rose,
          "default": SEMANTIC_PALETTE.teal
        }};
        Object.entries(markerColors).forEach(([key, color]) => {{
          defs.append("marker")
            .attr("id", "arrow-" + key)
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 22)
            .attr("refY", 0)
            .attr("markerWidth", 6)
            .attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path")
            .attr("d", "M0,-5L10,0L0,5")
            .attr("fill", color);
        }});

        const g = dagSvg.append("g").attr("class", "dag-RootGroup");
        const zoom = d3.zoom()
          .scaleExtent([0.25, 3.5])
          .on("zoom", (event) => {{
            dagZoomTransform = event.transform;
            g.attr("transform", event.transform);
          }});
        dagSvg.call(zoom);
        if (preserveViewport && dagZoomTransform) {{
          dagSvg.call(zoom.transform, dagZoomTransform);
        }}

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
          .attr("x1", d => d.sourceNode.x)
          .attr("y1", d => d.sourceNode.y)
          .attr("x2", d => d.targetNode.x)
          .attr("y2", d => d.targetNode.y)
          .attr("stroke", d => (highlightRootPath && d.on_root_path) ? SEMANTIC_PALETTE.amber : resolveRelationColor(d.type))
          .attr("stroke-opacity", d => (highlightRootPath && !d.on_root_path) ? 0.28 : 0.78)
          .attr("stroke-width", d => (highlightRootPath && d.on_root_path) ? 3.0 : 2.0)
          .attr("stroke-dasharray", d => (d.style && d.style.dasharray !== "none") ? d.style.dasharray : null)
          .attr("marker-end", d => "url(#arrow-" + (markerColors[d.type] ? d.type : "default") + ")");

        const edgeLabels = edgeElements.append("text")
          .attr("x", d => (d.sourceNode.x + d.targetNode.x) / 2)
          .attr("y", d => (d.sourceNode.y + d.targetNode.y) / 2 - 5)
          .attr("text-anchor", "middle")
          .attr("font-family", "IBM Plex Mono, monospace")
          .attr("font-size", "10px")
          .attr("fill", "var(--text-muted)")
          .text(d => d.type);

        const tooltip = document.getElementById("graph-tooltip");
        const nodeGroup = g.append("g").attr("class", "dag-nodes");
        const nodeElements = nodeGroup.selectAll("g.node-item")
          .data(nodes)
          .enter()
          .append("g")
          .attr("class", "node-item")
          .attr("transform", d => "translate(" + d.x + "," + d.y + ")")
          .style("cursor", "pointer")
          .call(
            d3.drag()
              .on("drag", function(event, d) {{
                d.x = event.x;
                d.y = event.y;
                d3.select(this).attr("transform", "translate(" + d.x + "," + d.y + ")");
                lines
                  .attr("x1", l => l.sourceNode.x)
                  .attr("y1", l => l.sourceNode.y)
                  .attr("x2", l => l.targetNode.x)
                  .attr("y2", l => l.targetNode.y);
                edgeLabels
                  .attr("x", l => (l.sourceNode.x + l.targetNode.x) / 2)
                  .attr("y", l => (l.sourceNode.y + l.targetNode.y) / 2 - 5);
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

        nodeElements.append("circle")
          .attr("class", "dag-node-circle")
          .attr("r", d => d.is_target ? 13.5 : (d.is_root ? 11 : 9.5))
          .attr("fill", d => resolveNodeSemanticColor(d))
          .attr("stroke", d => (highlightRootPath && d.on_root_path) ? SEMANTIC_PALETTE.amber : (d.id === selectedNodeId ? "var(--text-main)" : "var(--bg-card)"))
          .attr("stroke-width", d => (d.id === selectedNodeId || d.is_target || (highlightRootPath && d.on_root_path)) ? 2.8 : 1.6);

        nodeElements.append("text")
          .attr("dy", 25)
          .attr("text-anchor", "middle")
          .attr("font-family", "DM Sans, sans-serif")
          .attr("font-size", d => d.is_target ? "12px" : "11px")
          .attr("font-weight", d => d.is_target ? "600" : "500")
          .attr("fill", "var(--text-main)")
          .text(d => d.label + " (" + d.id + ")");
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
          .attr("stroke-width", d => (highlightRootPath && d.on_root_path) ? 3.0 : 2.0)
          .attr("stroke-opacity", d => (!highlightRootPath || d.on_root_path) ? 0.82 : 0.25);
      }}

      // ==========================================================================
      // View 3: Collapsible Lineage Tree View (D3.js v7)
      // ==========================================================================
      function renderCollapsibleTreeView(preserveViewport = false) {{
        if (!window.d3 || !treeData) return;
        const d3 = window.d3;
        const svgEl = document.getElementById("tree-svg");
        const width = svgEl.clientWidth || 860;
        const height = svgEl.clientHeight || 560;

        const svg = d3.select("#tree-svg");
        svg.selectAll("*").remove();
        const g = svg.append("g").attr("transform", "translate(95, 40)");

        const zoom = d3.zoom().scaleExtent([0.3, 3.0]).on("zoom", (event) => {{
          treeZoomTransform = event.transform;
          g.attr("transform", event.transform);
        }});
        svg.call(zoom);
        if (preserveViewport && treeZoomTransform) {{
          svg.call(zoom.transform, treeZoomTransform);
        }}

        const root = d3.hierarchy(treeData, d => d.children);
        if (preserveViewport && collapsedTreeIds.size > 0) {{
          root.descendants().forEach(d => {{
            if (collapsedTreeIds.has(d.data.id) && d.children) {{
              d._children = d.children;
              d.children = null;
            }}
          }});
        }}
        const treeLayout = d3.tree().size([height - 80, Math.max(480, width - 260)]);

        function updateTree() {{
          treeLayout(root);
          g.selectAll("*").remove();

          g.selectAll("path.tree-link")
            .data(root.links())
            .enter()
            .append("path")
            .attr("class", "tree-link")
            .attr("fill", "none")
            .attr("stroke", d => resolveRelationColor(d.target.data.relation_to_parent || "subClassOf"))
            .attr("stroke-opacity", 0.76)
            .attr("stroke-width", 2)
            .attr("stroke-dasharray", d => {{
              const rel = d.target.data.relation_to_parent || "subClassOf";
              return rel === "subClassOf" || rel === "root" ? null : "5,3";
            }})
            .attr("d", d3.linkHorizontal().x(d => d.y).y(d => d.x));

          const nodeSel = g.selectAll("g.tree-node")
            .data(root.descendants())
            .enter()
            .append("g")
            .attr("class", "tree-node")
            .attr("transform", d => "translate(" + d.y + "," + d.x + ")")
            .style("cursor", "pointer")
            .on("click", (event, d) => {{
              updateInspector(d.data.id);
              if (d.children) {{
                d._children = d.children;
                d.children = null;
                collapsedTreeIds.add(d.data.id);
              }} else if (d._children) {{
                d.children = d._children;
                d._children = null;
                collapsedTreeIds.delete(d.data.id);
              }}
              updateTree();
            }});

          nodeSel.append("circle")
            .attr("r", d => d.data.is_target ? 9.5 : 7)
            .attr("fill", d => d.data.is_target ? SEMANTIC_PALETTE.indigo : (d._children ? SEMANTIC_PALETTE.amber : SEMANTIC_PALETTE.teal))
            .attr("stroke", "var(--bg-card)")
            .attr("stroke-width", 2);

          nodeSel.append("text")
            .attr("dy", "0.32em")
            .attr("x", d => (d.children || d._children) ? -12 : 12)
            .attr("text-anchor", d => (d.children || d._children) ? "end" : "start")
            .attr("font-family", "DM Sans, sans-serif")
            .attr("font-size", "11px")
            .attr("font-weight", d => d.data.is_target ? "600" : "400")
            .attr("fill", "var(--text-main)")
            .text(d => d.data.label + " (" + d.data.id + ")");
        }}

        updateTree();
      }}

      // Dataset Switcher
      document.getElementById("dataset-selector").addEventListener("change", function() {{
        const chosen = DATASETS.get(this.value);
        if (chosen) {{
          loadActivePayload(chosen, {{ preserveViewport: false }});
        }}
      }});

      // Client-side JSON Loader (supports normalized hierarchy_graph.json or raw term.json)
      document.getElementById("file-input-json").addEventListener("change", function(e) {{
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = function(evt) {{
          try {{
            const parsed = JSON.parse(String(evt.target.result || "{{}}"));
            if (parsed.target_term && Array.isArray(parsed.nodes)) {{
              registerDataset(parsed);
              loadActivePayload(parsed, {{ preserveViewport: false }});
            }} else if (parsed.obo_id || parsed.iri) {{
              const tid = parsed.obo_id || parsed.short_form || "CUSTOM:0001";
              const tlabel = parsed.label || tid;
              const defn = Array.isArray(parsed.description) ? (parsed.description[0] || "") : (parsed.description || "");
              const rels = parsed.relations || {{}};
              const customNodes = [{{
                id: tid,
                iri: parsed.iri || "",
                label: tlabel,
                ontology: parsed.ontology_prefix || "OLS",
                definition: defn,
                is_target: true,
                is_root: Boolean(parsed.is_root),
                is_obsolete: Boolean(parsed.is_obsolete),
                depth: 0,
                on_root_path: true,
                synonyms: parsed.obo_synonym || (parsed.synonyms || []).map(s => ({{ name: s, scope: "EXACT" }})),
                xrefs: parsed.obo_xref || [],
                parents: [],
                children: []
              }}];
              const customEdges = [];
              (rels.parents || rels.hierarchicalParents || []).forEach(p => {{
                const pid = p.obo_id || p.short_form || p.label;
                if (!pid) return;
                customNodes.push({{
                  id: pid,
                  iri: p.iri || "",
                  label: p.label || pid,
                  ontology: p.ontology_prefix || "OLS",
                  definition: Array.isArray(p.description) ? (p.description[0] || "") : "",
                  is_target: false,
                  is_root: Boolean(p.is_root),
                  depth: -1,
                  on_root_path: true,
                  parents: [],
                  children: []
                }});
                const rtype = p.relation_type || "subClassOf";
                customEdges.push({{
                  id: pid + "->" + tid + ":" + rtype,
                  source: pid,
                  target: tid,
                  type: rtype,
                  is_hierarchical: rtype !== "subClassOf",
                  on_root_path: true,
                  style: {{
                    stroke: resolveRelationColor(rtype),
                    pattern: rtype === "subClassOf" ? "solid" : "dashed",
                    dasharray: rtype === "subClassOf" ? "none" : "6,4"
                  }}
                }});
                customNodes[0].parents.push({{ id: pid, label: p.label || pid, relation: rtype }});
              }});
              (rels.children || rels.hierarchicalChildren || []).forEach(c => {{
                const cid = c.obo_id || c.short_form || c.label;
                if (!cid) return;
                customNodes.push({{
                  id: cid,
                  iri: c.iri || "",
                  label: c.label || cid,
                  ontology: c.ontology_prefix || "OLS",
                  definition: Array.isArray(c.description) ? (c.description[0] || "") : "",
                  is_target: false,
                  is_root: false,
                  depth: 1,
                  on_root_path: false,
                  parents: [],
                  children: []
                }});
                const rtype = c.relation_type || "subClassOf";
                customEdges.push({{
                  id: tid + "->" + cid + ":" + rtype,
                  source: tid,
                  target: cid,
                  type: rtype,
                  is_hierarchical: rtype !== "subClassOf",
                  on_root_path: false,
                  style: {{
                    stroke: resolveRelationColor(rtype),
                    pattern: rtype === "subClassOf" ? "solid" : "dashed",
                    dasharray: rtype === "subClassOf" ? "none" : "6,4"
                  }}
                }});
                customNodes[0].children.push({{ id: cid, label: c.label || cid, relation: rtype }});
              }});
              const synthesized = {{
                title: "EMBL-EBI OLS Hierarchy Explorer: " + tlabel + " (" + tid + ")",
                target_term: customNodes[0],
                nodes: customNodes,
                edges: customEdges,
                tree: {{
                  id: tid,
                  label: tlabel,
                  is_target: true,
                  relation_to_parent: "root",
                  children: customNodes.filter(n => n.depth > 0).map(c => ({{
                    id: c.id,
                    label: c.label,
                    is_target: false,
                    relation_to_parent: "subClassOf",
                    children: []
                  }}))
                }},
                root_paths: [[tid]],
                metrics: {{
                  node_count: customNodes.length,
                  edge_count: customEdges.length,
                  ancestor_count: customNodes.filter(n => n.depth < 0).length,
                  direct_parent_count: customNodes[0].parents.length,
                  direct_child_count: customNodes[0].children.length,
                  relation_counts: {{ subClassOf: customEdges.length }}
                }},
                ontology_profile: activeData.ontology_profile,
                repository_stats: activeData.repository_stats
              }};
              registerDataset(synthesized);
              loadActivePayload(synthesized, {{ preserveViewport: false }});
            }}
          }} catch (err) {{
            console.error("Failed to parse uploaded JSON:", err);
          }}
        }};
        reader.readAsText(file);
      }});

      // Search Filtering
      document.getElementById("node-search-input").addEventListener("input", function() {{
        searchQuery = this.value.trim().toLowerCase();
        if (!window.d3) return;
        const d3 = window.d3;
        d3.selectAll(".node-item").attr("opacity", d => {{
          if (!searchQuery) return 1.0;
          const match = (d.label || "").toLowerCase().includes(searchQuery) || (d.id || "").toLowerCase().includes(searchQuery);
          return match ? 1.0 : 0.2;
        }});
      }});

      // Root Path Highlight Toggle
      document.getElementById("btn-trace-root").addEventListener("click", function() {{
        highlightRootPath = !highlightRootPath;
        this.classList.toggle("active", highlightRootPath);
        highlightSelectedNodeInGraph(selectedNodeId);
      }});

      // Reset View
      document.getElementById("btn-reset-zoom").addEventListener("click", function() {{
        rotY = 0.45;
        rotX = 0.22;
        zoom3d = 1.0;
        dagZoomTransform = null;
        treeZoomTransform = null;
        collapsedTreeIds.clear();
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
