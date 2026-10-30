---
name: embl-ebi-ols-visualize
description: >
  Query and search the EMBL-EBI Ontology Lookup Service (OLS) for biomedical
  ontology terms, definitions, and hierarchies across 250+ ontologies (GO, DOID,
  HP, MONDO, CHEBI, CL, UBERON). Generates interactive standalone HTML5
  dashboards featuring 3D Network explorers, D3.js 2D Hierarchy DAGs,
  collapsible Lineage Trees, Input-to-Processed Data Pipeline inspectors,
  synonym tables, and cross-ontology xref inspectors. Use when the user asks to
  search, explore, navigate, or visualize ontology structures and relationships.
---

# EMBL-EBI Ontology Lookup Service (OLS) Visualize

## Overview
Provides programmatic queries and graphical visualizations for the EMBL-EBI Ontology Lookup Service (OLS4). Generates standalone interactive HTML5 dashboards (`dashboard.html`) featuring a 3D Network view, a zoomable 2D Hierarchy Directed Acyclic Graph (DAG) viewer, a collapsible Lineage Tree, a side-by-side Data Pipeline inspector (comparing raw OLS4 API inputs against normalized graph outputs), Corpus Metrics, a Light and Dark theme switcher, multi-relational edge categorization (`is-a` vs. `part_of`, `develops_from`, `regulates`), and cross-database clinical xref inspection.

## Prerequisites
1. **Python Environment**: Python 3.10+ with standard library (`urllib`). Optional: `polite-http`.
2. **License Guard**: Verify that `.licenses/embl_ebi_ols_visualize_LICENSE.txt` exists in the workspace root. If absent, display the licensing notice and create the file with an ISO timestamp before querying.

## Core Rules
- **Execute Utility Scripts**: Always invoke the provided Python scripts in `scripts/`. Do not run raw `curl` or un-rate-limited queries against the OLS API.
- **Process Data Before Rendering UI**: Always execute the data retrieval and normalization pipeline (`run_pipeline.py` or `get_term.py` -> `visualize_hierarchy.py` -> `generate_dashboard.py`) on the user's requested ontology term or keyword first, so that `dashboard.html` displays real processed data from the user's request.
- **Respect Rate Limits**: Enforce maximum 5 requests per second (0.2s spacing) in compliance with EMBL-EBI Terms of Use.
- **Relational Distinction**: Differentiate taxonomic relations (`subClassOf`) from transitive partonomic relations (`part_of`, `develops_from`) in visualizations.
- **Skill Attribution**: State in the output that the EMBL-EBI OLS Visualize skill was used, citing McLaughlin et al. (2025).

## Interactive Dashboard Views (`dashboard.html`)
The generated `dashboard.html` renders as a self-contained HTML5 application and provides:
1. **Header & Theme Switcher**: Displays canonical OBO ID, ontology badge, deprecation status, a dataset selector, a live `Load JSON` file importer, node search filter, root-path highlighter, and a three-icon Light, Dark, and System theme selector (`#theme-btn-light`, `#theme-btn-dark`, `#theme-btn-system`).
2. **3D Network (Structural Data Diagram)**: Interactive 3D spatial node-and-edge visualization (WebGL with 2D software projection fallback) where vertical elevation encodes topological depth from ontology roots to child terms and horizontal coordinates separate multi-parent branches, with orbit drag, scroll zoom, `Auto-Rotate`, and `Reset Camera` controls.
3. **2D Hierarchy (Interactive Relationship Node Map)**: Layered D3.js (v7) Directed Acyclic Graph with draggable nodes, directional arrowheads, and semantic edge styling (`#0D9488`, `#D97706`, `#059669`, `#4F46E5`, `#E11D48`).
4. **Lineage Tree (Taxonomic Lineage Tree)**: Expandable and collapsible D3.js hierarchical tree for top-down taxonomic navigation.
5. **Data Pipeline (Empirical Data Pipeline)**: Flat bento comparison of the raw skill input (`obo_id`, `iri`, double-encoded REST path, raw relation endpoint counts) and the processed graph output (normalized nodes with depths, deduplicated semantic edges).
6. **Corpus Metrics (Corpus & Quantitative Metrics)**: Visualizes active subgraph relation coordinate bar plots, a topological depth by relation concentration heatmap, defining ontology metadata, and global OLS4 repository statistics (`/v2/stats`).
7. **Split-Pane Term Inspector**: Clicking any node in the 3D Network, 2D Hierarchy, Lineage Tree, or Data Pipeline table updates the right-hand inspector with definitions, shortest root path breadcrumbs, clickable parent/child pills, scoped synonyms (`EXACT`, `BROAD`, `NARROW`, `RELATED`), and external clinical cross-references (MeSH, ICD-10, OMIM, UMLS, MedDRA).

## Workflows

### 1. Unified End-to-End Pipeline (Recommended)
Full term hierarchy profiling and interactive dashboard generation:
```bash
python3 scripts/run_pipeline.py --obo_id "GO:0005634" -o ./output/GO_0005634/
```

Disease term resolution and hierarchy visualization:
```bash
python3 scripts/run_pipeline.py --obo_id "DOID:9351" -o ./output/DOID_9351/
```

Keyword search with automatic entity resolution and visual dashboard:
```bash
python3 scripts/run_pipeline.py --query "apoptosis" --ontology go -o ./output/apoptosis/
```

Offline synthetic mock mode (for sandboxed testing without network egress):
```bash
python3 scripts/run_pipeline.py --obo_id "GO:0005634" -o ./output/mock_nucleus/ --mock
```

### 2. Modular Subcommands
Query individual endpoints directly using scripts under `scripts/`:
```bash
# Search terms across ontologies
python3 scripts/search_ols.py --query "diabetes" --rows 5 --output ./output/search.json

# Autocomplete suggestions
python3 scripts/suggest_ols.py --query "diabet" --rows 5 --output ./output/suggest.json

# Get term details with hierarchical relations
python3 scripts/get_term.py --obo_id "GO:0005634" --relations parents,children,ancestors --output ./output/term.json

# Generate standalone dashboard from term JSON
python3 scripts/generate_dashboard.py --term_json ./output/term.json -o ./dashboard.html
```
