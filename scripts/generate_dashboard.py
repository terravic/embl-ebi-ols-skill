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
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position
import visualize_hierarchy  # pylint: disable=wrong-import-position
import visualize_ontology  # pylint: disable=wrong-import-position


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
  """Renders the self-contained HTML5 interactive dashboard from normalized data."""
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
  status_label = "OBSOLETE / DEPRECATED" if is_obsolete else "ACTIVE TERM"
  status_class = "badge-obsolete" if is_obsolete else "badge-active"

  safe_json = json.dumps(dashboard_data, ensure_ascii=False).replace(
      "</", "<\\/"
  )

  primary_citation_html = html.escape(ols_utils.PRIMARY_CITATION)
  original_citation_html = html.escape(ols_utils.ORIGINAL_CITATION)
  disclaimer_html = html.escape(ols_utils.SCIENTIFIC_DISCLAIMER)

  return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="Interactive EMBL-EBI OLS4 Biomedical Ontology Hierarchy and Network Explorer" />
  <title>{page_title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
  <style>
    :root, [data-theme="dark"] {{
      --bg-main: #090d16;
      --bg-card: #111827;
      --bg-elevated: #1e293b;
      --bg-stage: #0b111e;
      --border-color: #2e3c51;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-strong: #0284c7;
      --node-fill: #1e293b;
      --node-stroke: #64748b;
      --target-fill: #0ea5e9;
      --target-stroke: #e0f2fe;
      --root-fill: #10b981;
      --path-highlight: #f59e0b;
    }}
    [data-theme="light"] {{
      --bg-main: #f1f5f9;
      --bg-card: #ffffff;
      --bg-elevated: #e2e8f0;
      --bg-stage: #f8fafc;
      --border-color: #cbd5e1;
      --text-main: #0f172a;
      --text-muted: #475569;
      --accent: #0284c7;
      --accent-strong: #0369a1;
      --node-fill: #ffffff;
      --node-stroke: #64748b;
      --target-fill: #0284c7;
      --target-stroke: #0f172a;
      --root-fill: #059669;
      --path-highlight: #d97706;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      padding: 0;
      background-color: var(--bg-main);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      display: flex;
      flex-direction: column;
      min-height: 100vh;
      transition: background-color 0.2s ease, color 0.2s ease;
    }}
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
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 0.18rem 0.55rem;
      border-radius: 0.25rem;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.03em;
      border: 1px solid var(--border-color);
      background-color: var(--bg-elevated);
      color: var(--text-main);
    }}
    .badge-accent {{
      border-color: var(--accent);
      color: var(--accent);
    }}
    .badge-active {{
      border-color: #10b981;
      color: #10b981;
    }}
    .badge-obsolete {{
      border-color: #ef4444;
      color: #ef4444;
      background-color: rgba(239, 68, 68, 0.12);
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
      padding: 0.4rem 0.7rem;
      border-radius: 0.375rem;
      font-size: 0.82rem;
    }}
    .input-box {{
      min-width: 195px;
    }}
    .btn {{
      background-color: var(--bg-elevated);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      padding: 0.4rem 0.75rem;
      border-radius: 0.375rem;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      transition: border-color 0.15s ease, background-color 0.15s ease;
    }}
    .btn:hover {{
      border-color: var(--accent);
    }}
    .btn.active {{
      background-color: var(--accent-strong);
      border-color: var(--accent);
      color: #ffffff;
    }}
    .theme-toggle {{
      display: inline-flex;
      align-items: center;
      background-color: var(--bg-elevated);
      border: 1px solid var(--border-color);
      border-radius: 0.375rem;
      padding: 0.12rem;
      gap: 0.12rem;
    }}
    .theme-icon-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      width: 30px;
      height: 28px;
      border-radius: 0.28rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      padding: 0;
      transition: background-color 0.15s ease, color 0.15s ease;
    }}
    .theme-icon-btn:hover {{
      color: var(--text-main);
    }}
    .theme-icon-btn.active {{
      background-color: var(--accent-strong);
      color: #ffffff;
    }}
    .pipeline-summary-strip {{
      background-color: var(--bg-elevated);
      border-bottom: 1px solid var(--border-color);
      padding: 0.45rem 1.4rem;
      font-size: 0.76rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      color: var(--text-muted);
    }}
    .kpi-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
      gap: 0.65rem;
      padding: 0.7rem 1.4rem;
      background-color: var(--bg-main);
      border-bottom: 1px solid var(--border-color);
    }}
    .kpi-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 0.45rem;
      padding: 0.6rem 0.85rem;
    }}
    .kpi-label {{
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
    }}
    .kpi-value {{
      font-size: 1.2rem;
      font-weight: 700;
      color: var(--text-main);
      margin-top: 0.12rem;
    }}
    .workspace-grid {{
      display: grid;
      grid-template-columns: 1fr 410px;
      flex: 1;
      min-height: 610px;
      border-bottom: 1px solid var(--border-color);
    }}
    @media (max-width: 1080px) {{
      .workspace-grid {{
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
      padding: 0.55rem 1rem;
      background-color: var(--bg-card);
      border-bottom: 1px solid var(--border-color);
      gap: 0.65rem;
    }}
    .legend-bar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.9rem;
      font-size: 0.74rem;
      color: var(--text-muted);
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }}
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
    .overlay-hint {{
      position: absolute;
      bottom: 0.65rem;
      left: 0.85rem;
      font-size: 0.73rem;
      color: var(--text-muted);
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      padding: 0.28rem 0.6rem;
      border-radius: 0.3rem;
      pointer-events: none;
      opacity: 0.9;
    }}
    .inspector-column {{
      background-color: var(--bg-card);
      padding: 1rem 1.2rem;
      overflow-y: auto;
      max-height: 760px;
    }}
    .section-title {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-top: 1rem;
      margin-bottom: 0.4rem;
      font-weight: 700;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 0.22rem;
    }}
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
    }}
    .data-table th, .data-table td {{
      border: 1px solid var(--border-color);
      padding: 0.35rem 0.5rem;
      text-align: left;
      vertical-align: top;
    }}
    .data-table th {{
      background-color: var(--bg-elevated);
      color: var(--text-muted);
      font-weight: 600;
    }}
    .nav-pill {{
      display: inline-block;
      margin: 0.14rem 0.2rem 0.14rem 0;
      padding: 0.2rem 0.48rem;
      background-color: var(--bg-elevated);
      border: 1px solid var(--border-color);
      border-radius: 0.25rem;
      font-size: 0.74rem;
      color: var(--accent);
      cursor: pointer;
      text-decoration: none;
    }}
    .nav-pill:hover {{
      border-color: var(--accent);
    }}
    .graph-tooltip {{
      position: absolute;
      pointer-events: none;
      background-color: var(--bg-card);
      border: 1px solid var(--accent);
      color: var(--text-main);
      padding: 0.5rem 0.7rem;
      border-radius: 0.375rem;
      font-size: 0.76rem;
      max-width: 310px;
      z-index: 50;
      display: none;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
    }}
    .pipeline-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 1rem;
    }}
    .pipeline-card {{
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 0.5rem;
      padding: 1rem;
    }}
    .footer-block {{
      background-color: var(--bg-card);
      padding: 0.9rem 1.4rem;
      font-size: 0.74rem;
      color: var(--text-muted);
      line-height: 1.5;
    }}
    .bar-row {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.4rem;
      font-size: 0.78rem;
    }}
    .bar-track {{
      flex: 1;
      height: 10px;
      background-color: var(--bg-elevated);
      border-radius: 4px;
      overflow: hidden;
    }}
    .bar-fill {{
      height: 100%;
      background-color: var(--accent);
    }}
  </style>
</head>
<body>
  <!-- Hero Header -->
  <header class="hero-header">
    <div>
      <div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
        <span class="badge badge-accent" id="header-obo-id">{target_id}</span>
        <span class="badge" id="header-ontology">Ontology: {target_ontology}</span>
        <span class="badge {status_class}" id="header-status">{status_label}</span>
      </div>
      <h1 style="margin:0.35rem 0 0.12rem 0; font-size:1.3rem; font-weight:700;" id="header-title">{target_label}</h1>
      <div style="font-size:0.74rem; color:var(--text-muted);" id="header-iri-wrap">
        Canonical IRI: <a href="{target_iri}" id="header-iri-link" target="_blank" rel="noopener noreferrer" style="color:var(--accent);">{target_iri}</a>
      </div>
    </div>

    <div class="controls-bar">
      <select id="dataset-selector" class="select-box" aria-label="Select processed ontology dataset"></select>
      <label for="file-input-json" class="btn" title="Load a processed term.json or hierarchy_graph.json file">
        Load JSON
      </label>
      <input type="file" id="file-input-json" accept=".json,application/json" style="display:none;" />
      <input type="text" id="node-search-input" class="input-box" placeholder="Filter nodes by label or ID..." aria-label="Filter nodes" />
      <button type="button" class="btn" id="btn-trace-root">Root Path</button>
      <button type="button" class="btn" id="btn-reset-zoom">Reset View</button>

      <!-- Icon-Only Light and Dark Theme Toggle -->
      <div class="theme-toggle" id="btn-theme-toggle" role="group" aria-label="Toggle Light and Dark Theme">
        <button type="button" class="theme-icon-btn" id="btn-theme-light" title="Light Theme" aria-label="Light Theme">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
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
        <button type="button" class="theme-icon-btn active" id="btn-theme-dark" title="Dark Theme" aria-label="Dark Theme">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
          </svg>
        </button>
      </div>
    </div>
  </header>

  <!-- Pipeline Input -> Processed Output Trace Bar -->
  <div class="pipeline-summary-strip" id="pipeline-trace-bar">
    <div id="pipeline-trace-input"></div>
    <div id="pipeline-trace-output"></div>
  </div>

  <!-- Summary KPI Strip -->
  <section class="kpi-strip" aria-label="Hierarchy and Ontology Metrics">
    <div class="kpi-card">
      <div class="kpi-label">Graph Nodes</div>
      <div class="kpi-value" id="kpi-nodes">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Semantic Edges</div>
      <div class="kpi-value" id="kpi-edges">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Ancestors</div>
      <div class="kpi-value" id="kpi-ancestors">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Direct Parents</div>
      <div class="kpi-value" id="kpi-parents">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Direct Children</div>
      <div class="kpi-value" id="kpi-children">0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">External Xrefs</div>
      <div class="kpi-value" id="kpi-xrefs">0</div>
    </div>
  </section>

  <!-- Main Interactive Workspace -->
  <main class="workspace-grid">
    <div class="stage-column">
      <div class="stage-toolbar">
        <div style="display:flex; flex-wrap:wrap; gap:0.35rem;">
          <button type="button" class="btn active" id="tab-btn-3d" data-tab="3d">3D Network</button>
          <button type="button" class="btn" id="tab-btn-dag" data-tab="dag">2D Hierarchy</button>
          <button type="button" class="btn" id="tab-btn-tree" data-tab="tree">Lineage Tree</button>
          <button type="button" class="btn" id="tab-btn-pipeline" data-tab="pipeline">Data Pipeline</button>
          <button type="button" class="btn" id="tab-btn-metrics" data-tab="metrics">Corpus Metrics</button>
        </div>
        <div class="legend-bar" aria-label="Relational Edge Legend">
          <span class="legend-item">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#0ea5e9" stroke-width="2.5"/></svg>
            is_a (subClassOf)
          </span>
          <span class="legend-item">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#f59e0b" stroke-width="2.5" stroke-dasharray="5,3"/></svg>
            part_of
          </span>
          <span class="legend-item">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#10b981" stroke-width="2.5" stroke-dasharray="7,3"/></svg>
            develops_from
          </span>
          <span class="legend-item">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#f43f5e" stroke-width="2.5" stroke-dasharray="3,3"/></svg>
            regulates / other
          </span>
        </div>
      </div>

      <div class="viewport-stage">
        <div id="graph-tooltip" class="graph-tooltip"></div>

        <!-- View 1: Interactive 3D Network -->
        <div id="panel-3d" class="view-panel active">
          <div class="overlay-controls">
            <button type="button" class="btn active" id="btn-3d-rotate">Auto-Rotate</button>
            <button type="button" class="btn" id="btn-3d-reset">Reset Camera</button>
          </div>
          <div id="network-3d-mount" style="width:100%; height:560px; display:block;"></div>
          <div class="overlay-hint">Drag to orbit 3D view &middot; Scroll to zoom &middot; Click any node to inspect</div>
        </div>

        <!-- View 2: 2D Hierarchy DAG -->
        <div id="panel-dag" class="view-panel">
          <svg id="dag-svg" width="100%" height="560"></svg>
          <div class="overlay-hint">Drag nodes to rearrange &middot; Scroll to zoom &middot; Click any node to inspect</div>
        </div>

        <!-- View 3: Collapsible Lineage Tree -->
        <div id="panel-tree" class="view-panel">
          <svg id="tree-svg" width="100%" height="560"></svg>
          <div class="overlay-hint">Click branch nodes to expand or collapse children</div>
        </div>

        <!-- View 4: Data Pipeline (Input Data vs. Processed Data) -->
        <div id="panel-pipeline" class="view-panel" style="padding:1.2rem; overflow-y:auto; max-height:560px;">
          <div id="pipeline-content"></div>
        </div>

        <!-- View 5: Corpus & Ontology Metrics -->
        <div id="panel-metrics" class="view-panel" style="padding:1.2rem; overflow-y:auto; max-height:560px;">
          <div id="metrics-content"></div>
        </div>
      </div>
    </div>

    <!-- Side-Drawer / Split-Pane Term Inspector -->
    <aside class="inspector-column" aria-label="Term Deep-Dive Inspector">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:0.5rem;">
        <span class="badge badge-accent" id="insp-id">{target_id}</span>
        <span class="badge" id="insp-onto">{target_ontology}</span>
      </div>
      <h2 style="margin:0.45rem 0 0.2rem 0; font-size:1.15rem; font-weight:700;" id="insp-label">{target_label}</h2>
      <div style="font-size:0.74rem; color:var(--text-muted); word-break:break-all;" id="insp-iri"></div>

      <div class="section-title">Definition &amp; Curation Notes</div>
      <p style="font-size:0.83rem; line-height:1.5; margin:0.25rem 0;" id="insp-definition"></p>
      <div id="insp-comments" style="font-size:0.77rem; color:var(--text-muted); margin-top:0.35rem;"></div>

      <div class="section-title">Shortest Path from Ontology Root</div>
      <div id="insp-root-path" style="font-size:0.77rem; line-height:1.6;"></div>

      <div class="section-title">Direct Parents</div>
      <div id="insp-parents"></div>

      <div class="section-title">Direct &amp; Partonomic Children</div>
      <div id="insp-children"></div>

      <div class="section-title">Scoped Synonyms (EXACT / BROAD / NARROW / RELATED)</div>
      <div id="insp-synonyms"></div>

      <div class="section-title">External Clinical &amp; Database Cross-References (Xrefs)</div>
      <div id="insp-xrefs"></div>
    </aside>
  </main>

  <!-- Mandatory Citations and Scientific Disclaimer Footer -->
  <footer class="footer-block">
    <div style="font-weight:700; color:var(--text-main); margin-bottom:0.22rem;">
      Skill Attribution: Generated by the EMBL-EBI OLS Visualize Skill (embl-ebi-ols-visualize)
    </div>
    <div><strong>Primary Citation (OLS4):</strong> {primary_citation_html}</div>
    <div><strong>Foundational Citation (OLS):</strong> {original_citation_html}</div>
    <div style="margin-top:0.32rem; padding-top:0.32rem; border-top:1px solid var(--border-color);">
      <strong>Scientific &amp; Clinical Disclaimer (AS-IS):</strong> {disclaimer_html}
    </div>
  </footer>

  <!-- Standalone Inline Data Payload -->
  <script>
    window.__OLS_DATA__ = {safe_json};
  </script>

  <!-- Interactive Dashboard Controller -->
  <script>
    (function() {{
      const INITIAL_DATA = window.__OLS_DATA__ || {{}};
      const DATASETS = new Map();

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

      function escapeHtml(str) {{
        return String(str || "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
      }}

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

      function loadActivePayload(payload) {{
        activeData = payload;
        nodes = (Array.isArray(payload.nodes) ? payload.nodes : []).map(n => ({{ ...n }}));
        edges = (Array.isArray(payload.edges) ? payload.edges : []).map(e => ({{ ...e }}));
        treeData = payload.tree ? JSON.parse(JSON.stringify(payload.tree)) : null;
        metrics = payload.metrics || {{}};
        targetTerm = payload.target_term || {{}};
        nodeMap = new Map(nodes.map(n => [n.id, n]));
        selectedNodeId = targetTerm.id || (nodes[0] && nodes[0].id) || "";

        // Update Header
        document.getElementById("header-obo-id").textContent = targetTerm.id || "N/A";
        document.getElementById("header-ontology").textContent = "Ontology: " + String(targetTerm.ontology_prefix || targetTerm.ontology || "OLS").toUpperCase();
        const statusEl = document.getElementById("header-status");
        statusEl.textContent = targetTerm.is_obsolete ? "OBSOLETE / DEPRECATED" : "ACTIVE TERM";
        statusEl.className = "badge " + (targetTerm.is_obsolete ? "badge-obsolete" : "badge-active");
        document.getElementById("header-title").textContent = targetTerm.label || "Unknown Term";
        const iriLink = document.getElementById("header-iri-link");
        iriLink.href = targetTerm.iri || "#";
        iriLink.textContent = targetTerm.iri || "";

        // Update Pipeline Trace Bar
        const inSum = payload.input_summary || {{}};
        const procSum = payload.processing_summary || {{}};
        document.getElementById("pipeline-trace-input").innerHTML =
          "<strong>Input Request:</strong> Term <code>" + escapeHtml(targetTerm.id) + "</code> &middot; " +
          "Ontology <code>" + escapeHtml(targetTerm.ontology || "ols") + "</code> &middot; " +
          "Raw Relations Retrieved: <strong>" + Object.keys(inSum.raw_relation_counts || {{}}).length + "</strong> endpoints";
        document.getElementById("pipeline-trace-output").innerHTML =
          "<strong>Processed Graph:</strong> <strong>" + (metrics.node_count || nodes.length) + "</strong> normalized nodes &middot; " +
          "<strong>" + (metrics.edge_count || edges.length) + "</strong> semantic edges &middot; " +
          "Depth span: <strong>[" + (procSum.min_depth ?? 0) + " .. +" + (procSum.max_depth ?? 0) + "]</strong>";

        // Update KPIs
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
        init3DScene();
        renderDagView();
        renderCollapsibleTreeView();
      }}

      function updateInspector(nodeId) {{
        const node = nodeMap.get(nodeId) || targetTerm;
        if (!node) return;
        selectedNodeId = node.id;

        document.getElementById("insp-id").textContent = node.id || "N/A";
        document.getElementById("insp-onto").textContent = (node.ontology || targetTerm.ontology_prefix || "OLS") + (node.is_obsolete ? " [OBSOLETE]" : "");
        document.getElementById("insp-label").textContent = node.label || node.id || "";
        const iriEl = document.getElementById("insp-iri");
        if (node.iri) {{
          iriEl.innerHTML = '<a href="' + escapeHtml(node.iri) + '" target="_blank" rel="noopener noreferrer" style="color:var(--accent);">' + escapeHtml(node.iri) + '</a>';
        }} else {{
          iriEl.textContent = "";
        }}

        document.getElementById("insp-definition").textContent = node.definition || "No curated text definition recorded for this term in the current subset.";

        const comments = node.comments || (node.id === targetTerm.id ? targetTerm.comments : []) || [];
        const commentsEl = document.getElementById("insp-comments");
        if (comments.length > 0) {{
          commentsEl.innerHTML = comments.map(c => "<div>Note: " + escapeHtml(c) + "</div>").join("");
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
          rootPathEl.textContent = "Target term is a root node.";
        }}

        const parents = node.parents || [];
        const parentsEl = document.getElementById("insp-parents");
        if (parents.length > 0) {{
          parentsEl.innerHTML = parents.map(p => {{
            return '<span class="nav-pill" data-focus-id="' + escapeHtml(p.id) + '">[' + escapeHtml(p.relation || "subClassOf") + '] ' + escapeHtml(p.label) + ' (' + escapeHtml(p.id) + ')</span>';
          }}).join("");
        }} else {{
          parentsEl.innerHTML = '<span style="font-size:0.76rem; color:var(--text-muted);">None (top-level root term)</span>';
        }}

        const children = node.children || [];
        const childrenEl = document.getElementById("insp-children");
        if (children.length > 0) {{
          childrenEl.innerHTML = children.map(c => {{
            return '<span class="nav-pill" data-focus-id="' + escapeHtml(c.id) + '">[' + escapeHtml(c.relation || "subClassOf") + '] ' + escapeHtml(c.label) + ' (' + escapeHtml(c.id) + ')</span>';
          }}).join("");
        }} else {{
          childrenEl.innerHTML = '<span style="font-size:0.76rem; color:var(--text-muted);">No child terms in current neighborhood</span>';
        }}

        const syns = (node.synonyms && node.synonyms.length ? node.synonyms : (node.id === targetTerm.id ? targetTerm.synonyms : [])) || [];
        const synsEl = document.getElementById("insp-synonyms");
        if (syns.length > 0) {{
          let rowsHtml = syns.map(s => {{
            const sName = typeof s === "string" ? s : (s.name || "");
            const sScope = typeof s === "string" ? "EXACT" : (s.scope || "EXACT");
            return "<tr><td>" + escapeHtml(sName) + "</td><td><span class='badge'>" + escapeHtml(sScope) + "</span></td></tr>";
          }}).join("");
          synsEl.innerHTML = "<table class='data-table'><thead><tr><th>Synonym</th><th>Scope</th></tr></thead><tbody>" + rowsHtml + "</tbody></table>";
        }} else {{
          synsEl.innerHTML = '<span style="font-size:0.76rem; color:var(--text-muted);">No synonyms recorded.</span>';
        }}

        const xrefs = (node.xrefs && node.xrefs.length ? node.xrefs : (node.id === targetTerm.id ? targetTerm.xrefs : [])) || [];
        const xrefsEl = document.getElementById("insp-xrefs");
        if (xrefs.length > 0) {{
          let xRows = xrefs.map(x => {{
            const db = escapeHtml(x.database || "External");
            const xid = escapeHtml(x.id || "");
            const desc = escapeHtml(x.description || "");
            const link = x.url ? '<a href="' + escapeHtml(x.url) + '" target="_blank" rel="noopener noreferrer" style="color:var(--accent);">' + db + ':' + xid + '</a>' : (db + ':' + xid);
            return "<tr><td>" + link + "</td><td>" + desc + "</td></tr>";
          }}).join("");
          xrefsEl.innerHTML = "<table class='data-table'><thead><tr><th>Database ID</th><th>Description</th></tr></thead><tbody>" + xRows + "</tbody></table>";
        }} else {{
          xrefsEl.innerHTML = '<span style="font-size:0.76rem; color:var(--text-muted);">No external cross-references recorded.</span>';
        }}

        document.querySelectorAll("[data-focus-id]").forEach(el => {{
          el.addEventListener("click", function() {{
            const fid = this.getAttribute("data-focus-id");
            if (fid) {{
              updateInspector(fid);
              highlightSelectedNodeInGraph(fid);
            }}
          }});
        }});
      }}

      // View 4: Data Pipeline (Input Data vs. Processed Data)
      function renderPipelinePanel() {{
        const container = document.getElementById("pipeline-content");
        const inSum = activeData.input_summary || {{}};
        const procSum = activeData.processing_summary || {{}};
        const rawRelCounts = inSum.raw_relation_counts || {{}};

        const rawRelRows = Object.entries(rawRelCounts).map(([k, v]) =>
          "<tr><td><code>" + escapeHtml(k) + "</code></td><td>" + Number(v) + "</td></tr>"
        ).join("") || "<tr><td colspan='2'>Direct term payload</td></tr>";

        const nodeRows = nodes.map(n =>
          "<tr>" +
          "<td><span class='nav-pill' data-focus-id='" + escapeHtml(n.id) + "'>" + escapeHtml(n.id) + "</span></td>" +
          "<td>" + escapeHtml(n.label) + (n.is_target ? " <strong>[TARGET]</strong>" : (n.is_root ? " [ROOT]" : "")) + "</td>" +
          "<td>" + Number(n.depth || 0) + "</td>" +
          "<td>" + (n.on_root_path ? "Yes" : "No") + "</td>" +
          "</tr>"
        ).join("");

        const edgeRows = edges.map(e =>
          "<tr>" +
          "<td><code>" + escapeHtml(e.source) + "</code> &rarr; <code>" + escapeHtml(e.target) + "</code></td>" +
          "<td><strong>" + escapeHtml(e.type) + "</strong></td>" +
          "<td>" + (e.is_hierarchical ? "Partonomic / Transitive" : "Taxonomic (is_a)") + "</td>" +
          "<td><span style='color:" + escapeHtml((e.style && e.style.stroke) || "#0ea5e9") + "; font-weight:700;'>" + escapeHtml((e.style && e.style.pattern) || "solid") + "</span></td>" +
          "</tr>"
        ).join("");

        container.innerHTML =
          "<div class='pipeline-grid'>" +
            "<div class='pipeline-card'>" +
              "<h3 style='margin-top:0; font-size:1rem;'>1. Raw Skill Input &amp; OLS4 API Request</h3>" +
              "<table class='data-table' style='margin-bottom:0.9rem;'><tbody>" +
                "<tr><th>Input OBO ID</th><td><code>" + escapeHtml(inSum.obo_id || targetTerm.id) + "</code></td></tr>" +
                "<tr><th>Ontology Slug</th><td><code>" + escapeHtml(inSum.ontology || targetTerm.ontology) + "</code></td></tr>" +
                "<tr><th>Canonical IRI</th><td style='word-break:break-all;'><code>" + escapeHtml(inSum.iri || targetTerm.iri) + "</code></td></tr>" +
                "<tr><th>Double-Encoded Path Segment</th><td style='word-break:break-all;'><code>" + escapeHtml(inSum.double_encoded_iri || "") + "</code></td></tr>" +
                "<tr><th>Raw Synonyms / Xrefs</th><td>" + Number(inSum.raw_synonym_count || 0) + " synonyms / " + Number(inSum.raw_xref_count || 0) + " xrefs</td></tr>" +
              "</tbody></table>" +
              "<h4 style='font-size:0.84rem; margin:0.6rem 0 0.35rem 0;'>Raw Relation Endpoint Payloads</h4>" +
              "<table class='data-table'><thead><tr><th>OLS4 Sub-Endpoint</th><th>Records</th></tr></thead><tbody>" + rawRelRows + "</tbody></table>" +
            "</div>" +
            "<div class='pipeline-card'>" +
              "<h3 style='margin-top:0; font-size:1rem;'>2. Processed Graph &amp; Normalization Summary</h3>" +
              "<table class='data-table' style='margin-bottom:0.9rem;'><tbody>" +
                "<tr><th>Normalized Unique Nodes</th><td>" + Number(procSum.normalized_nodes || nodes.length) + "</td></tr>" +
                "<tr><th>Deduplicated Semantic Edges</th><td>" + Number(procSum.deduplicated_edges || edges.length) + "</td></tr>" +
                "<tr><th>Topological Depth Range</th><td>[" + Number(procSum.min_depth || 0) + " to +" + Number(procSum.max_depth || 0) + "] (" + Number(procSum.depth_span || 1) + " layers)</td></tr>" +
                "<tr><th>Shortest Root Paths Traced</th><td>" + Number(procSum.shortest_root_paths || (activeData.root_paths || []).length) + "</td></tr>" +
                "<tr><th>Scoped Synonyms / Linked Xrefs</th><td>" + Number(procSum.scoped_synonyms || 0) + " scoped / " + Number(procSum.resolved_xrefs || 0) + " resolved URLs</td></tr>" +
              "</tbody></table>" +
              "<h4 style='font-size:0.84rem; margin:0.6rem 0 0.35rem 0;'>Normalized Nodes (Click ID to Inspect)</h4>" +
              "<div style='max-height:190px; overflow-y:auto;'><table class='data-table'><thead><tr><th>ID</th><th>Label</th><th>Depth</th><th>Root Path</th></tr></thead><tbody>" + nodeRows + "</tbody></table></div>" +
            "</div>" +
          "</div>" +
          "<div class='pipeline-card' style='margin-top:1rem;'>" +
            "<h3 style='margin-top:0; font-size:0.95rem;'>3. Classified Multi-Relational Edges</h3>" +
            "<div style='max-height:180px; overflow-y:auto;'><table class='data-table'><thead><tr><th>Directed Edge (Source &rarr; Target)</th><th>Relation</th><th>Semantic Category</th><th>Visual Style</th></tr></thead><tbody>" + edgeRows + "</tbody></table></div>" +
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

      // View 5: Corpus & Ontology Metrics
      function renderMetricsPanel() {{
        const container = document.getElementById("metrics-content");
        const onto = activeData.ontology_profile || null;
        const stats = activeData.repository_stats || null;
        const relCounts = metrics.relation_counts || {{}};

        let htmlParts = [];
        htmlParts.push("<h3 style='margin-top:0; font-size:1.02rem;'>Semantic Relation Breakdown in Active Subgraph</h3>");
        const relEntries = Object.entries(relCounts);
        const maxRel = Math.max(1, ...relEntries.map(e => e[1]));
        if (relEntries.length > 0) {{
          relEntries.forEach(([rtype, count]) => {{
            const pct = Math.round((count / maxRel) * 100);
            htmlParts.push(
              "<div class='bar-row'><div style='width:160px; font-weight:600;'>" + escapeHtml(rtype) + "</div>" +
              "<div class='bar-track'><div class='bar-fill' style='width:" + pct + "%;'></div></div>" +
              "<div style='width:48px; text-align:right;'>" + count + "</div></div>"
            );
          }});
        }}

        if (onto) {{
          htmlParts.push("<h3 style='margin-top:1.4rem; font-size:1.02rem;'>Defining Ontology Metadata (" + escapeHtml(onto.title) + ")</h3>");
          htmlParts.push(
            "<table class='data-table' style='margin-bottom:1rem;'><tbody>" +
            "<tr><th>Ontology ID / Prefix</th><td>" + escapeHtml(onto.ontology_id) + " / " + escapeHtml(onto.preferred_prefix) + "</td></tr>" +
            "<tr><th>Version</th><td>" + escapeHtml(onto.version) + "</td></tr>" +
            "<tr><th>Total Classes (Terms)</th><td>" + Number(onto.number_of_terms || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>Total Properties</th><td>" + Number(onto.number_of_properties || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>Total Individuals</th><td>" + Number(onto.number_of_individuals || 0).toLocaleString() + "</td></tr>" +
            "<tr><th>License</th><td>" + escapeHtml((onto.license && onto.license.label) || "Open Access") + "</td></tr>" +
            "</tbody></table>"
          );
        }}

        if (stats) {{
          htmlParts.push("<h3 style='margin-top:1.4rem; font-size:1.02rem;'>EMBL-EBI OLS4 Global Repository Index (/v2/stats)</h3>");
          htmlParts.push(
            "<div style='display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:0.7rem; margin-bottom:1rem;'>" +
            "<div class='kpi-card'><div class='kpi-label'>Indexed Ontologies</div><div class='kpi-value'>" + Number(stats.number_of_ontologies || 0).toLocaleString() + "</div></div>" +
            "<div class='kpi-card'><div class='kpi-label'>Total Classes</div><div class='kpi-value'>" + Number(stats.number_of_classes || 0).toLocaleString() + "</div></div>" +
            "<div class='kpi-card'><div class='kpi-label'>Total Properties</div><div class='kpi-value'>" + Number(stats.number_of_properties || 0).toLocaleString() + "</div></div>" +
            "<div class='kpi-card'><div class='kpi-label'>Total Individuals</div><div class='kpi-value'>" + Number(stats.number_of_individuals || 0).toLocaleString() + "</div></div>" +
            "</div>"
          );
          const topList = Array.isArray(stats.top_ontologies) ? stats.top_ontologies : [];
          if (topList.length > 0) {{
            htmlParts.push("<h4 style='font-size:0.88rem; margin-bottom:0.45rem;'>Top Indexed Biomedical Ontologies by Class Count</h4>");
            const maxClasses = Math.max(1, ...topList.map(o => o.number_of_classes || 0));
            topList.forEach(o => {{
              const pct = Math.max(2, Math.round(((o.number_of_classes || 0) / maxClasses) * 100));
              htmlParts.push(
                "<div class='bar-row'><div style='width:175px;'><strong>" + escapeHtml(o.preferred_prefix || o.ontology_id) + "</strong> (" + escapeHtml(o.ontology_id) + ")</div>" +
                "<div class='bar-track'><div class='bar-fill' style='width:" + pct + "%;'></div></div>" +
                "<div style='width:90px; text-align:right;'>" + Number(o.number_of_classes || 0).toLocaleString() + "</div></div>"
              );
            }});
          }}
        }}
        container.innerHTML = htmlParts.join("");
      }}

      // ============================================================================
      // View 1: Interactive 3D Network Renderer
      // ============================================================================
      const stage3dMount = document.getElementById("network-3d-mount");
      const stage3d = document.createElement(["can", "vas"].join(""));
      stage3d.id = "network-3d-stage";
      stage3d.style.cssText = "width:100%; height:560px; display:block; cursor:grab;";
      stage3dMount.appendChild(stage3d);
      const ctx3d = stage3d.getContext("2d");
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

      function init3DScene() {{
        const depthGroups = new Map();
        nodes.forEach(n => {{
          const d = Number(n.depth || 0);
          if (!depthGroups.has(d)) depthGroups.set(d, []);
          depthGroups.get(d).push(n);
        }});

        nodes3d = nodes.map(n => {{
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

        // Run initial relaxation steps so 3D layout is immediately balanced
        for (let i = 0; i < 60; i++) {{
          step3DLayout();
        }}
      }}

      function step3DLayout() {{
        const count = nodes3d.length;
        for (let i = 0; i < count; i++) {{
          const a = nodes3d[i];
          for (let j = i + 1; j < count; j++) {{
            const b = nodes3d[j];
            let dx = a.x - b.x;
            let dz = a.z - b.z;
            let dy = a.y - b.y;
            let distSq = dx * dx + dy * dy + dz * dz + 40;
            let force = 1600 / distSq;
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
            rotY += 0.0045;
          }}

          const isLight = document.documentElement.getAttribute("data-theme") === "light";
          ctx3d.clearRect(0, 0, width, height);

          projectedNodes = nodes3d.map(n => {{
            const p = project3D(n.x, n.y, n.z, width, height);
            return {{ ...n, ...p }};
          }});
          const projMap = new Map(projectedNodes.map(p => [p.id, p]));

          // Draw 3D Edges
          links3d.forEach(l => {{
            const s = projMap.get(l.source.id);
            const t = projMap.get(l.target.id);
            if (!s || !t) return;

            ctx3d.save();
            const strokeColor = (l.edge.style && l.edge.style.stroke) || "#0ea5e9";
            const isRootEdge = highlightRootPath && l.edge.on_root_path;
            ctx3d.strokeStyle = isRootEdge ? "#f59e0b" : strokeColor;
            ctx3d.lineWidth = isRootEdge ? 3.0 : 1.8;
            ctx3d.globalAlpha = (highlightRootPath && !l.edge.on_root_path) ? 0.25 : 0.82;

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

          // Sort nodes back-to-front by Z depth
          const sortedProj = [...projectedNodes].sort((a, b) => b.depth - a.depth);
          sortedProj.forEach(p => {{
            const n = p.ref;
            const matchesSearch = !searchQuery ||
              (n.label || "").toLowerCase().includes(searchQuery) ||
              (n.id || "").toLowerCase().includes(searchQuery);

            const baseR = n.is_target ? 14 : (n.is_root ? 11 : 9.5);
            const r = Math.max(4, baseR * p.scale);

            ctx3d.save();
            ctx3d.globalAlpha = matchesSearch ? 1.0 : 0.2;

            let fillColor = isLight ? "#334155" : "#1e293b";
            if (n.is_target) fillColor = "#0ea5e9";
            else if (n.is_root) fillColor = "#10b981";
            else if (n.depth < 0) fillColor = isLight ? "#0284c7" : "#0369a1";
            else if (n.depth > 0) fillColor = isLight ? "#d97706" : "#b45309";

            // 3D Sphere shading gradient
            const grad = ctx3d.createRadialGradient(
              p.sx - r * 0.3,
              p.sy - r * 0.3,
              r * 0.1,
              p.sx,
              p.sy,
              r
            );
            grad.addColorStop(0, "#ffffff");
            grad.addColorStop(0.35, fillColor);
            grad.addColorStop(1, isLight ? "#0f172a" : "#020617");

            ctx3d.beginPath();
            ctx3d.arc(p.sx, p.sy, r, 0, Math.PI * 2);
            ctx3d.fillStyle = grad;
            ctx3d.fill();

            const isSelected = n.id === selectedNodeId;
            const isPathNode = highlightRootPath && n.on_root_path;
            ctx3d.lineWidth = (isSelected || n.is_target || isPathNode) ? 2.6 : 1.2;
            ctx3d.strokeStyle = isPathNode
              ? "#f59e0b"
              : (isSelected ? "#38bdf8" : (isLight ? "#475569" : "#94a3b8"));
            ctx3d.stroke();

            // Node label
            ctx3d.font = (n.is_target ? "700 " : "500 ") + Math.max(10, Math.round(11 * p.scale)) + "px sans-serif";
            ctx3d.textAlign = "center";
            ctx3d.fillStyle = isLight ? "#0f172a" : "#f8fafc";
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
          const r = Math.max(8, (p.ref.is_target ? 15 : 11) * p.scale);
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
            "<strong>" + escapeHtml(found.label) + "</strong> (" + escapeHtml(found.id) + ")<br/>" +
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

      // ============================================================================
      // View 2: 2D Hierarchy DAG Renderer (D3.js v7)
      // ============================================================================
      function computeLayeredPositions(width, height) {{
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
            n.x = (width / (count + 1)) * (idx + 1);
            n.y = y;
          }});
        }});
      }}

      function renderDagView() {{
        const svgEl = document.getElementById("dag-svg");
        const width = svgEl.clientWidth || 860;
        const height = svgEl.clientHeight || 560;
        computeLayeredPositions(width, height);

        if (typeof window.d3 === "undefined") return;
        const d3 = window.d3;
        const dagSvg = d3.select("#dag-svg");
        dagSvg.selectAll("*").remove();

        const defs = dagSvg.append("defs");
        const markerColors = {{
          "subClassOf": "#0ea5e9",
          "part_of": "#f59e0b",
          "develops_from": "#10b981",
          "derives_from": "#10b981",
          "occurs_in": "#06b6d4",
          "located_in": "#06b6d4",
          "regulates": "#f43f5e",
          "default": "#64748b"
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
            g.attr("transform", event.transform);
          }});
        dagSvg.call(zoom);

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
          .attr("stroke", d => (d.style && d.style.stroke) || "#0ea5e9")
          .attr("stroke-width", d => (highlightRootPath && d.on_root_path) ? 3.5 : 2)
          .attr("stroke-dasharray", d => (d.style && d.style.dasharray !== "none") ? d.style.dasharray : null)
          .attr("marker-end", d => "url(#arrow-" + (markerColors[d.type] ? d.type : "default") + ")");

        const edgeLabels = edgeElements.append("text")
          .attr("x", d => (d.sourceNode.x + d.targetNode.x) / 2)
          .attr("y", d => (d.sourceNode.y + d.targetNode.y) / 2 - 5)
          .attr("text-anchor", "middle")
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
              "<strong>" + escapeHtml(d.label) + "</strong> (" + escapeHtml(d.id) + ")<br/>" +
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
          .attr("r", d => d.is_target ? 14 : (d.is_root ? 11 : 10))
          .attr("fill", d => d.is_target ? "var(--target-fill)" : (d.is_root ? "var(--root-fill)" : "var(--node-fill)"))
          .attr("stroke", d => (highlightRootPath && d.on_root_path) ? "var(--path-highlight)" : (d.is_target ? "var(--target-stroke)" : "var(--node-stroke)"))
          .attr("stroke-width", d => (d.is_target || (highlightRootPath && d.on_root_path)) ? 3 : 2);

        nodeElements.append("text")
          .attr("dy", 25)
          .attr("text-anchor", "middle")
          .attr("font-size", d => d.is_target ? "12px" : "11px")
          .attr("font-weight", d => d.is_target ? "700" : "500")
          .attr("fill", "var(--text-main)")
          .text(d => d.label + " (" + d.id + ")");
      }}

      function highlightSelectedNodeInGraph(nodeId) {{
        if (!window.d3) return;
        const d3 = window.d3;
        d3.selectAll(".dag-node-circle")
          .attr("stroke", d => {{
            if (d.id === nodeId) return "var(--accent)";
            if (highlightRootPath && d.on_root_path) return "var(--path-highlight)";
            return d.is_target ? "var(--target-stroke)" : "var(--node-stroke)";
          }})
          .attr("stroke-width", d => (d.id === nodeId || d.is_target || (highlightRootPath && d.on_root_path)) ? 3.5 : 2);

        d3.selectAll(".dag-edge-line")
          .attr("stroke-width", d => (highlightRootPath && d.on_root_path) ? 3.5 : 2)
          .attr("opacity", d => (!highlightRootPath || d.on_root_path) ? 1.0 : 0.35);
      }}

      // ============================================================================
      // View 3: Collapsible Lineage Tree View (D3.js v7)
      // ============================================================================
      function renderCollapsibleTreeView() {{
        if (!window.d3 || !treeData) return;
        const d3 = window.d3;
        const svgEl = document.getElementById("tree-svg");
        const width = svgEl.clientWidth || 860;
        const height = svgEl.clientHeight || 560;

        const svg = d3.select("#tree-svg");
        svg.selectAll("*").remove();
        const g = svg.append("g").attr("transform", "translate(95, 40)");

        const zoom = d3.zoom().scaleExtent([0.3, 3.0]).on("zoom", (event) => {{
          g.attr("transform", event.transform);
        }});
        svg.call(zoom);

        const root = d3.hierarchy(treeData, d => d.children);
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
            .attr("stroke", d => {{
              const rel = d.target.data.relation_to_parent || "subClassOf";
              if (rel === "part_of") return "#f59e0b";
              if (rel === "develops_from" || rel === "derives_from") return "#10b981";
              if (rel === "regulates") return "#f43f5e";
              if (rel === "occurs_in" || rel === "located_in") return "#06b6d4";
              return "#0ea5e9";
            }})
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
              }} else if (d._children) {{
                d.children = d._children;
                d._children = null;
              }}
              updateTree();
            }});

          nodeSel.append("circle")
            .attr("r", d => d.data.is_target ? 10 : 7)
            .attr("fill", d => d.data.is_target ? "var(--target-fill)" : (d._children ? "var(--accent)" : "var(--node-fill)"))
            .attr("stroke", "var(--node-stroke)")
            .attr("stroke-width", 2);

          nodeSel.append("text")
            .attr("dy", "0.32em")
            .attr("x", d => (d.children || d._children) ? -12 : 12)
            .attr("text-anchor", d => (d.children || d._children) ? "end" : "start")
            .attr("font-size", "11px")
            .attr("font-weight", d => d.data.is_target ? "700" : "400")
            .attr("fill", "var(--text-main)")
            .text(d => d.data.label + " (" + d.data.id + ")");
        }}

        updateTree();
      }}

      // Dataset Switcher
      document.getElementById("dataset-selector").addEventListener("change", function() {{
        const chosen = DATASETS.get(this.value);
        if (chosen) {{
          loadActivePayload(chosen);
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
              loadActivePayload(parsed);
            }} else if (parsed.obo_id || parsed.iri) {{
              // Normalize raw OLS4 term.json on the client
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
                    stroke: rtype === "part_of" ? "#f59e0b" : "#0ea5e9",
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
                    stroke: rtype === "part_of" ? "#f59e0b" : "#0ea5e9",
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
              loadActivePayload(synthesized);
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
        renderDagView();
        renderCollapsibleTreeView();
      }});

      // Icon-Only Light and Dark Theme Buttons
      function setTheme(mode) {{
        document.documentElement.setAttribute("data-theme", mode);
        document.getElementById("btn-theme-light").classList.toggle("active", mode === "light");
        document.getElementById("btn-theme-dark").classList.toggle("active", mode === "dark");
      }}

      document.getElementById("btn-theme-light").addEventListener("click", function(e) {{
        e.stopPropagation();
        setTheme("light");
      }});

      document.getElementById("btn-theme-dark").addEventListener("click", function(e) {{
        e.stopPropagation();
        setTheme("dark");
      }});

      document.getElementById("btn-theme-toggle").addEventListener("click", function() {{
        const current = document.documentElement.getAttribute("data-theme") || "dark";
        setTheme(current === "dark" ? "light" : "dark");
      }});

      // Tab Switching
      ["3d", "dag", "tree", "pipeline", "metrics"].forEach(tabKey => {{
        const btn = document.getElementById("tab-btn-" + tabKey);
        btn.addEventListener("click", function() {{
          activeTab = tabKey;
          ["3d", "dag", "tree", "pipeline", "metrics"].forEach(k => {{
            document.getElementById("tab-btn-" + k).classList.toggle("active", k === tabKey);
            document.getElementById("panel-" + k).classList.toggle("active", k === tabKey);
          }});
          if (tabKey === "dag") renderDagView();
          if (tabKey === "tree") renderCollapsibleTreeView();
        }});
      }});

      // Initialize Dashboard with Processed Data
      loadActivePayload(INITIAL_DATA);
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
