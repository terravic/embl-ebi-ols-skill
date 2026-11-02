# Product Requirement Document: EMBL-EBI OLS Visualize Skill (`embl-ebi-ols-visualize`)

| Document Attribute | Value |
| :--- | :--- |
| **Product Name** | EMBL-EBI Ontology Lookup Service (OLS) Visualize (`embl-ebi-ols-visualize`) |
| **Version** | 1.2.0 |
| **License** | Apache License 2.0 |
| **Target Platforms** | Standardized Agent Skill Harnesses and Command-Line Environments |
| **Upstream API** | EMBL-EBI OLS4 REST API (`https://www.ebi.ac.uk/ols4/api`) |
| **Design Specification** | `DESIGN.md` (Visual Hierarchy, Theme System, and Semantic Data Visualization Rules) |

---

## 1. Executive Overview

The `embl-ebi-ols-visualize` skill is a biomedical ontology query, traversal, and visualization toolkit built for agentic workflows and command-line analysis. It provides programmatic access to the European Bioinformatics Institute (EMBL-EBI) Ontology Lookup Service (OLS4) across more than 280 biomedical ontologies--including the Gene Ontology (GO), Human Disease Ontology (DOID), Human Phenotype Ontology (HP), Mondo Disease Ontology (MONDO), Chemical Entities of Biological Interest (CHEBI), Cell Ontology (CL), Uber-anatomy Ontology (UBERON), Experimental Factor Ontology (EFO), and NCI Thesaurus (NCIT)--by pairing rate-limited REST API retrieval with a graph normalization pipeline and a standalone HTML5 interactive dashboard (`dashboard.html`).

Where raw REST API responses return deeply nested JSON structures that obscure multiple inheritance and transitive partonomic relationships, `embl-ebi-ols-visualize` normalizes ontology lineages into Directed Acyclic Graphs (DAGs) and collapsible hierarchical trees, visually distinguishes taxonomic (`subClassOf` / `is-a`) edges from transitive (`part_of`, `develops_from`, `derives_from`, `occurs_in`, `regulates`) relationships using a standardized semantic color palette, tracks input-to-output data pipeline metrics, surfaces cross-database clinical cross-references (MeSH, ICD-10, OMIM, UMLS, MedDRA), supports incremental state updates via Server-Sent Events (SSE), and displays only data returned by the live OLS4 API or contained in a user-uploaded file, with three clearly labelled bundled examples.

---

## 2. User Stories & Scope

### 2.1 Target Audience

| Audience Segment | Profile | Primary Interaction Mode |
| :--- | :--- | :--- |
| **Non-Technical Biomedical Researchers & Clinicians** | Translational scientists, geneticists, and disease curators who require visual exploration of ontology hierarchies, term definitions, synonyms, and clinical database mappings without writing code. | Natural language prompts inside an agent skill harness rendering the interactive `dashboard.html` output. |
| **Technical Bioinformaticians & Ontology Engineers** | Computational biologists and data engineers integrating standardized ontology lookups, ancestor/descendant traversals, and corpus metrics into automated pipelines. | Direct command-line execution of `scripts/run_pipeline.py` and modular endpoint scripts (`get_term.py`, `search_ols.py`, `visualize_hierarchy.py`). |
| **Agent Harness & Platform Engineers** | Systems engineers deploying and testing agent skills in continuous integration environments. | Automated test suites (`pytest` / `unittest`) that replace the HTTP transport with recorded OLS4 responses; the skill itself always queries the live API. |

### 2.2 User Stories

| Story ID | Persona | Requirement Statement | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **US-01** | Biomedical Researcher | As a researcher studying cellular compartments, I want to look up `GO:0005634` (nucleus) and inspect its parent and child terms in an interactive graph so that I can distinguish direct subclass relations from `part_of` structural components. | Executing `run_pipeline.py --obo_id "GO:0005634" -o ./output/nucleus/` produces `dashboard.html` with interactive Structural Data Diagram (3D Network), Interactive Relationship Node Map (2D Hierarchy DAG), and Lineage Tree views where `subClassOf` edges are solid Vibrant Teal (`#0D9488`) and `part_of` edges are dashed Energetic Amber (`#D97706`). |
| **US-02** | Disease Curator | As a disease ontology curator, I want to examine `DOID:9351` (diabetes mellitus), its multi-parent disease classifications, synonyms, and external cross-references (ICD-10, MeSH, OMIM, UMLS) in a single view. | Clicking any node in `dashboard.html` updates the Split-Pane Term Inspector displaying canonical label, OBO ID, definition, scoped synonyms (`EXACT`, `BROAD`, `NARROW`, `RELATED`), external xrefs, direct parents, and direct children. |
| **US-03** | Translational Scientist | As a user who knows a biological concept keyword (e.g., `"apoptosis"`) rather than an OBO identifier, I want the skill to resolve the keyword to its canonical ontology term and build the hierarchy automatically. | Running `run_pipeline.py --query "apoptosis" --ontology go -o ./output/apoptosis/` resolves `"apoptosis"` to `GO:0006915`, fetches its hierarchical neighborhood, and generates `dashboard.html`. |
| **US-04** | Ontology Engineer | As an ontology engineer evaluating repository coverage, I want to profile ontology metadata (version, class count, property count, root terms, license) alongside global OLS4 index statistics and inspect raw-to-normalized data pipeline metrics. | Running `run_pipeline.py --ontology go --stats -o ./output/go_overview/` aggregates `/ontologies/go` and `/v2/stats` metrics into the Corpus Metrics and Data Pipeline views. |
| **US-05** | Platform Engineer | As an engineer running automated regression checks, I want the test suite to run without network access while the shipped skill only ever shows real OLS4 data. | `python3 -m unittest discover -s tests` passes offline by patching `ols_utils._http_get` with `tests/fake_ols_api.py`; production scripts reject `--mock`, and an unreachable API produces an error (exit `1`) rather than substitute data. |
| **US-06** | Compliance Officer | As a governance reviewer, I want the skill to verify workspace license notices before running queries and include academic citations and scientific disclaimers in all outputs. | `.licenses/embl_ebi_ols_visualize_LICENSE.txt` is verified or created prior to execution, and every generated dashboard and CLI summary includes McLaughlin et al. (2025) and Jupp et al. (2015) citations plus the scientific disclaimer. |

### 2.3 Scope Definition

#### In-Scope Capabilities
1. **Complete OLS4 Endpoint Coverage**: Command-line wrappers for `/search` (`search_ols.py`), `/suggest` (`suggest_ols.py`), `/ontologies/{id}/terms/{iri}` and sub-relations (`get_term.py`), `/ontologies/{id}/properties/{iri}` (`get_property.py`), `/ontologies/{id}/individuals/{iri}` (`get_individual.py`), `/ontologies/{id}` (`get_ontology.py`), and `/v2/stats` (`get_stats.py`).
2. **Protocol & Rate-Limit Compliance**: Strict 5.0 QPS rate limiting (minimum 0.2 seconds between HTTP requests), exponential backoff retry on HTTP 429/503 responses, automatic OBO ID to canonical IRI conversion, and double URL-encoding of IRI path segments.
3. **Graph & Tree Normalization Engine**: Extraction of unique term nodes with topological depth calculation, shortest-path-to-root tracing, semantic edge categorization (`subClassOf`, `part_of`, `develops_from`, `derives_from`, `occurs_in`, `located_in`, `regulates`), input-to-processed pipeline summary metadata (`input_summary`, `processing_summary`), and conversion of multi-parent DAGs into rooted tree hierarchies (`visualize_hierarchy.py`).
4. **Ontology Corpus & Statistics Profiler**: Aggregation of ontology metadata, root class distributions, and repository-wide statistics (`visualize_ontology.py`).
5. **Standalone HTML5 Interactive Dashboard**: Generation of a self-contained `dashboard.html` file (`generate_dashboard.py`) following the `DESIGN.md` visual hierarchy: typography (`DM Sans`, `Instrument Serif`, `IBM Plex Mono` with `tabular-nums`), single-level grid layout, three-icon theme switcher (`#theme-btn-light`, `#theme-btn-dark`, `#theme-btn-system`) with OS appearance tracking and a `system_theme` fallback, data visualization palette (`#0D9488`, `#D97706`, `#4F46E5`, `#059669`, `#E11D48`), five synchronized views (`Structural Data Diagram` / 3D Network, `Interactive Relationship Node Map` / 2D Hierarchy, `Lineage Tree`, `Data Pipeline`, `Corpus Metrics`), client-side JSON loading, live SSE incremental state updates, a term inspector, and a citation footer.
6. **Unified Pipeline Orchestrator**: Single-command orchestration from keyword or OBO ID input to normalized JSON datasets and `dashboard.html` output (`run_pipeline.py`).
7. **Live-Data Integrity**: All displayed values come from the live OLS4 API or a user-uploaded file. Missing values stay empty, lineage edges come only from OLS4 (`/graph`, `/parents`, `/hierarchicalParents`, and each ancestor's parents via `--lineage`), and no placeholder terms, roots, or metadata are generated.
8. **Isolated Example Datasets**: Three bundled terms in `sample_data/` (`GO:0005634`, `DOID:9351`, `GO:0006915`) appear in the dashboard's **Examples** group, tagged `source: "example"`. They never contribute data to live or uploaded datasets.
9. **In-Browser Upload Processing**: `Load JSON` accepts a raw OLS4 `term.json` or a processed `hierarchy_graph.json` and builds the graph, depths, relation counts, root paths, and trees from that file alone, using the same rules as `visualize_hierarchy.py`.
10. **Zoom-Dependent Labels**: In the 3D, 2D, and tree views, labels keep a constant on-screen size and are placed greedily in priority order (selected node, target term, search matches, root path, ontology roots, then by depth); a label that would overlap a node or another label is hidden. Each label tries several positions (below, above, right, left). Detail grows with zoom: name only, then OBO ID and relation type, then a short definition; relation names on 2D edges appear when zoomed in.
11. **Lineage-First Tree**: The Lineage Tree opens with the root-to-term path and the term's children expanded, using the term's deepest occurrence when it appears under several top-level ancestors. Other branches start collapsed with a hidden-child count such as `(+3)`.
12. **Fit-to-View Camera**: The 3D view frames the bounding sphere of all nodes; `Reset Camera` and `Reset View` restore a view in which every node is visible at any rotation, and wheel zoom ranges from 0.2x to 12x of that framing. The 2D and tree views also open fitted to the panel.

#### Out-of-Scope Capabilities
1. **Ontology Authoring or OWL Reasoning**: Modifying upstream ontologies, running Description Logic (DL) reasoners (e.g., ELK, HermiT) locally on raw `.owl` or `.obo` files, or submitting write/mutation requests to EMBL-EBI servers.
2. **Clinical Decision Support**: Providing patient-specific medical diagnoses, clinical treatment recommendations, or processing Protected Health Information (PHI) / Personally Identifiable Information (PII).
3. **Stateful Database Hosting**: Running persistent database servers; the output is a self-contained HTML5 file suitable for direct rendering from disk or over HTTP with optional Server-Sent Events (SSE).

---

## 3. Technical Architecture

### 3.1 System Component & Data Flow Diagram

```text
+-----------------------------------------------------------------------------------+
|                           AGENT HARNESS / CLI USER                                |
|        (Natural Language Prompt -> SKILL.md -> CLI Invocation)                    |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                     UNIFIED PIPELINE ORCHESTRATOR                                 |
|                         (scripts/run_pipeline.py)                                 |
+-------+-------------------------+-----------------------+-------------------------+
        | 1. Pre-flight Guard     | 2. Entity & Relation  | 3. Data Transformation
        v                         |    Retrieval          |    & HTML Synthesis
+-------------------------------+ |                       |
| LICENSE VERIFICATION GUARD    | |                       |
| (ols_utils.verify_license_    | |                       |
|  guard -> .licenses/...)      | |                       |
+-------------------------------+ |                       |
                                  v                       |
+-------------------------------------------------------+ |
| BASELINE OLS4 API WRAPPERS                            | |
| - scripts/search_ols.py      (/search)                | |
| - scripts/suggest_ols.py     (/suggest)               | |
| - scripts/get_term.py        (/terms/{iri} + rels)    | |
| - scripts/get_property.py    (/properties/{iri})      | |
| - scripts/get_individual.py  (/individuals/{iri})     | |
| - scripts/get_ontology.py    (/ontologies/{id})       | |
| - scripts/get_stats.py       (/v2/stats)              | |
+---------------------------+---------------------------+ |
                            |                             |
                            v                             |
+-------------------------------------------------------+ |
| SHARED TRANSPORT (scripts/ols_utils.py)               | |
| - OBO Prefix Resolution & Canonical IRI Mapper        | |
| - Double URL-Encoder (http%253A%252F%252F...)         | |
| - 5.0 QPS Rate Limiter (0.2s spacing + backoff)       | |
| - polite-http client with urllib.request fallback     | |
+-------------+-----------------------------------------+ |
              |                                           |
              v                                           |
+---------------------------+                             |
| EMBL-EBI OLS4 REST API    |                             |
| https://www.ebi.ac.uk/    |                             |
| ols4/api                  |                             |
+---------------------------+                             |
                                                          v
+-----------------------------------------------------------------------------------+
|                     ANALYTICAL & VISUALIZATION MODULES                            |
|  +-------------------------------------+  +------------------------------------+  |
|  | scripts/visualize_hierarchy.py      |  | scripts/visualize_ontology.py      |  |
|  | - Node & Depth Extraction           |  | - Ontology Summary Metrics         |  |
|  | - Semantic Edge Classification      |  | - Root Distribution Profiling      |  |
|  | - Root Path Tracer & Tree Builder   |  | - Global Repository Stats          |  |
|  | - Input vs. Processed Trace Summary |  |                                    |  |
|  +------------------+------------------+  +-----------------+------------------+  |
|                     |                                       |                     |
|                     +-------------------+-------------------+                     |
|                                         |                                         |
|                                         v                                         |
|  +-----------------------------------------------------------------------------+  |
|  | scripts/generate_dashboard.py                                               |  |
|  | - Inline JSON State Injection (window.__OLS_DATA__ + system_theme)          |  |
|  | - Light, Dark, and System Theme Selector (#theme-btn-light/-dark/-system)   |  |
|  | - WebGL + 2D Fallback Structural Data Diagram, 2D Node Map, Lineage Tree    |  |
|  | - Data Pipeline, Corpus Metrics Heatmap, SSE Streaming & Term Inspector     |  |
|  +--------------------------------------+--------------------------------------+  |
+-----------------------------------------|-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                        DELIVERABLE OUTPUTS (output_dir/)                          |
|  - term.json / ontology.json / stats.json / hierarchy_graph.json                  |
|  - dashboard.html (Standalone Interactive HTML5 Dashboard)                        |
+-----------------------------------------------------------------------------------+
```

### 3.2 Sequence of Operations (`run_pipeline.py`)

```text
User / Agent      run_pipeline.py      ols_utils.py       get_term / search     visualize_*      generate_dashboard.py
     |                   |                  |                     |                  |                     |
     |-- CLI Request --->|                  |                     |                  |                     |
     |                   |-- verify_guard ->|                     |                  |                     |
     |                   |<-- Guard OK -----|                     |                  |                     |
     |                   |                  |                     |                  |                     |
     |                   |-- [If --query]: resolve_query -------->|                  |                     |
     |                   |                  |<-- make_request ----|                  |                     |
     |                   |<-- Resolved OBO ID / IRI --------------|                  |                     |
     |                   |                  |                     |                  |                     |
     |                   |-- Fetch term + relations ------------->|                  |                     |
     |                   |                  |<-- make_request ----|                  |                     |
     |                   |<-- Term & Relation Payload ------------|                  |                     |
     |                   |                  |                     |                  |                     |
     |                   |-- Build Normalized DAG & Tree -------------------------->|                     |
     |                   |<-- Graph Nodes, Typed Edges, Rooted Tree, Trace --------|                     |
     |                   |                  |                     |                  |                     |
     |                   |-- [If --stats]: Profile Ontology & Global Stats -------->|                     |
     |                   |<-- Ontology Summary & Corpus Distribution ---------------|                     |
     |                   |                  |                     |                  |                     |
     |                   |-- Render Standalone HTML5 Dashboard ------------------------------------------>|
     |                   |<-- Written dashboard.html -----------------------------------------------------|
     |<-- Summary + Path |                  |                     |                  |                     |
```

---

## 4. Functional Requirements

### 4.1 Data Inputs

| Input Parameter | Applicable Scripts | Data Type & Format | Description |
| :--- | :--- | :--- | :--- |
| `--obo_id` | `get_term.py`, `get_property.py`, `get_individual.py`, `run_pipeline.py` | String (`PREFIX:LOCAL_ID`, e.g., `GO:0005634`, `DOID:9351`) | Canonical OBO identifier. Automatically mapped to `http://purl.obolibrary.org/obo/PREFIX_LOCAL_ID` and ontology prefix. |
| `--iri` | `get_term.py`, `get_property.py`, `get_individual.py`, `run_pipeline.py` | String (Absolute URI, e.g., `http://purl.obolibrary.org/obo/GO_0005634`) | Full canonical resource IRI. Double URL-encoded before insertion into REST path segments. |
| `--query` / `-q` | `search_ols.py`, `suggest_ols.py`, `run_pipeline.py` | String (Non-empty keyword or phrase) | Search term for full-text lookup, prefix autocomplete, or two-step entity resolution. |
| `--ontology` | All lookup/search scripts, `run_pipeline.py` | String (Lowercase slug, e.g., `go`, `doid`, `hp`, `mondo`, `chebi`) | Target ontology identifier. Required when `--iri` is used without a standard OBO prefix or for ontology-specific profiling. |
| `--relations` | `get_term.py`, `run_pipeline.py` | Comma-separated String | Hierarchical sub-resources to retrieve: `parents`, `children`, `ancestors`, `descendants`, `hierarchicalParents`, `hierarchicalChildren`, `hierarchicalAncestors`, `hierarchicalDescendants`, `graph`. |
| `--exact`, `--defining`, `--obsolete`, `--local` | `search_ols.py` | Boolean flags | Search filters controlling exact label/synonym matching, defining ontology isolation, obsolete term inclusion, and local term constraints. |
| `--childrenOf`, `--allChildrenOf` | `search_ols.py` | String (IRI or OBO ID) | Restricts search results to direct or transitive children of a specified parent term. |
| `--rows`, `--start` | `search_ols.py`, `suggest_ols.py`, `get_ontology.py` | Integer (`rows >= 1`, `start >= 0`) | Pagination controls for paged HAL endpoints. |
| `--stats` | `run_pipeline.py` | Boolean flag | Fetches `/ontologies/{id}` and `/v2/stats` to include repository-wide and ontology-level statistical charts in the dashboard. |
| `--lineage` | `get_term.py` (always on in `run_pipeline.py`) | Boolean flag | Also fetches `/parents` and `/hierarchicalParents` for every ancestor so the full root-to-term lineage is connected by real OLS4 edges. |
| `--output` / `-o` / `--output_dir` | All CLI scripts | File or Directory Path | Destination relative or local file path (individual scripts) or directory path (`run_pipeline.py`) for generated outputs. |

### 4.2 Processing Stages

1. **Stage 1: License Guard Verification (`ols_utils.verify_license_guard`)**
   - Inspects the workspace root directory for `.licenses/embl_ebi_ols_visualize_LICENSE.txt` (or `.licenses/embl_ebi_ols_LICENSE.txt`).
   - If neither file exists, logs the EMBL-EBI OLS Terms of Use notice and writes `.licenses/embl_ebi_ols_visualize_LICENSE.txt` with an ISO 8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`).

2. **Stage 2: Entity Resolution & IRI Encoding (`ols_utils.py`, `search_ols.py`)**
   - When `--obo_id` is supplied, validates the `PREFIX:ID` structure, resolves the ontology slug via `OBO_PREFIX_TO_ONTOLOGY` (supporting `GO`, `DOID`, `EFO`, `HP`, `CHEBI`, `MONDO`, `NCIT`, `CL`, `UBERON`, `SO`, `PR`, `PATO`, `MP`, `OBI`, `BFO`, `IAO`, `ENVO`, `PO`, `CLO`, `DUO`, or dynamic lowercase fallback), converts to canonical IRI `http://purl.obolibrary.org/obo/{PREFIX}_{ID}`, and applies `double_encode_iri()`.
   - When `--query` is supplied to `run_pipeline.py` without `--obo_id` or `--iri`, executes an exact search first and falls back to standard full-text search if no exact match exists, selecting the top defining ontology class match.

3. **Stage 3: Multi-Relation Retrieval (`get_term.py`)**
   - Fetches the primary term payload from `/ontologies/{ontology}/terms/{double_encoded_iri}`.
   - Iterates through requested `--relations` (`parents`, `children`, `ancestors`, `descendants`, `hierarchicalParents`, `hierarchicalChildren`, `hierarchicalAncestors`, `hierarchicalDescendants`, `graph`), unwrapping HAL `_embedded.terms` arrays and attaching them under `term_data["relations"][rel_name]`.
   - With `--lineage` (always enabled by `run_pipeline.py`), fetches `/parents` and `/hierarchicalParents` for each ancestor and stores them under `term_data["relations"]["lineage"]`, so ancestor-to-ancestor edges come from OLS4. The pipeline's default relation set is `parents,children,ancestors,hierarchicalParents,hierarchicalChildren,hierarchicalAncestors,graph`.

4. **Stage 4: Graph & Hierarchical Tree Transformation (`visualize_hierarchy.py`)**
   - Extracts unique nodes across the focal term, relation lists, and optional `graph` block. Each node record contains `id`, `iri`, `label`, `ontology`, `definition`, `synonyms`, `obo_synonym`, `xrefs`, `is_obsolete`, `is_root`, `is_target`, and `depth` (negative integers for ancestors, `0` for focal target, positive integers for descendants).
   - Extracts and deduplicates directed edges (`source` -> `target`, oriented from parent/whole to child/part) only from OLS4 data: `/graph` edges (serialized subject -> object and reversed for display, except `has part`), `/parents` and `/children` (is-a), `/hierarchicalParents` and `/hierarchicalChildren`, and `lineage` records. Each edge is classified with the `DESIGN.md` data visualization palette:
     - `subClassOf` (`is_a`): Taxonomic inheritance, `is_hierarchical=False`, style `solid`, color `#0D9488` (Vibrant Teal).
     - `part_of`: Meronymic containment, `is_hierarchical=True`, style `dashed` (`6,4`), color `#D97706` (Energetic Amber).
     - `develops_from` / `derives_from`: Lineage development, `is_hierarchical=True`, style `dashed` (`8,4`), color `#059669` (Functional Emerald).
     - `occurs_in` / `located_in`: Spatial/compartmental localization, `is_hierarchical=True`, style `dotted` (`3,3`), color `#4F46E5` (Vivid Indigo).
     - `regulates` / `positively_regulates` / `negatively_regulates`: Regulatory relations, `is_hierarchical=True`, style `dotted` (`4,3`), color `#E11D48` (Deep Rose).
     - `hierarchical`: OLS4 hierarchical relation whose property is not stated in the response, style `dashed` (`2,3`), color `#D97706`.
     - Any other relation (e.g., `has part`, `in taxon`): kept with its OLS4 label, style `dotted` (`4,3`), neutral color `#78716C`.
   - Drops fetched terms that no edge connects and reports their count in `processing_summary.unconnected_nodes`; no lineage links are inferred.
   - Computes shortest paths from the top-level nodes of the subgraph (in-degree `0`) to the focal term via Breadth-First Search (BFS), marking nodes and edges along root paths (`on_root_path=True`). The `is_root` flag is kept exactly as reported by OLS4.
   - Builds `input_summary` and `processing_summary` blocks comparing raw OLS4 API inputs against normalized graph metrics.
   - Builds a cycle-safe forest `trees` (one tree per top-level node; no virtual root) with `id`, `name`, `label`, `relation_to_parent`, `is_target`, `on_root_path`, and `children`, cloning shared subtrees when a node has multiple inheritance.

5. **Stage 5: Ontology & Repository Statistics Profiling (`visualize_ontology.py`)**
   - Parses ontology metadata (`get_ontology.py`) and global statistics (`get_stats.py`) into normalized metrics (`number_of_terms`, `number_of_properties`, `number_of_individuals`, `version`, `updated`, `license`) and root terms. Fields absent from the response are left empty or `null`.

6. **Stage 6: Standalone HTML5 Dashboard Synthesis (`generate_dashboard.py`)**
   - Reads desktop-environment appearance settings where available (`detect_host_system_theme()`: `GTK_THEME`, `gsettings`, `kdeglobals`) as a fallback for webviews without `prefers-color-scheme`, and serializes normalized term, `input_summary`, `processing_summary`, graph, tree, root-path, ontology, stats, and `system_theme` payloads into `window.__OLS_DATA__` with safe `<script>` tag escaping.
   - Attaches the three bundled example datasets under `examples`, each tagged `source: "example"` and carrying only its own metadata. The active payload is tagged `source: "live"`.
   - Emits `dashboard.html` following `DESIGN.md`:
     - **Typography & Surface Hierarchy**: Pairs `DM Sans` (UI prose/controls), `Instrument Serif` (display titles/headers), and `IBM Plex Mono` (`font-variant-numeric: tabular-nums` for numerical/tabular data) over flat single-level grid panes with `1px solid` borders (`6px` to `8px` radius) and thin horizontal table row dividers.
     - **Three-Icon Theme Selector**: Segmented control (`#theme-btn-light`, `#theme-btn-dark`, `#theme-btn-system`) with Sun, Crescent Moon, and Monitor SVGs, `aria-pressed` state, `localStorage` persistence, real-time `window.matchMedia('(prefers-color-scheme: dark)')` listener, and exact Light (`#FAFAF9`, `#FFFFFF`, `#E7E5E4`, `#1C1917`, `#787774`) and Dark (`#0D0E11`, `#16171D`, `#292A30`, `#ECE8E2`, `#9A9895`) surface tokens.
     - **Structural Data Diagram (`3D Network`)**: Interactive 3D spatial view with hardware WebGL bond rendering paired with a deterministic 2D software projection fallback, orbit rotation, scroll zoom, `Auto-Rotate`, and a fit-to-view `Reset Camera` control.
     - **Interactive Relationship Node Map (`2D Hierarchy`)**: Layered D3.js v7 SVG DAG; wide depth layers wrap into rows of at most 10 nodes. Supports node dragging, zoom/pan, search filtering, and root-path highlighting.
     - **Lineage Tree**: Collapsible D3.js forest with fixed node spacing, opening on the root-to-term lineage.
     - **Data Pipeline**: Side-by-side comparison of raw OLS4 input parameters/counts and processed graph nodes/edges.
     - **Corpus Metrics**: Transparent-background SVG bar plots with subtle axis gridlines (`#E7E5E4` light / `#292A30` dark), a depth-by-relation heatmap transitioning from the active surface tone through `#0D9488` and `#4F46E5` to `#E11D48`, and, when present, ontology metadata and global OLS4 repository statistics (`/v2/stats`).
     - **Dataset Selector and `Load JSON`**: Datasets are grouped as **Loaded** and **Examples**; an `Example` or `Uploaded file` badge identifies the source of the active dataset.
     - **Split-Pane Term Inspector**: Displays canonical definitions, shortest root path breadcrumbs, clickable parent/child pills, scoped synonyms, and external clinical cross-references.
     - **Live SSE & Incremental State Updates**: Supports `EventSource` live streaming and `window.__OLS_DASHBOARD_API__.pushIncrementalUpdate()` without resetting user viewport state, scroll position, or active chart/camera interactions.

### 4.3 Validation Rules

1. **Identifier Validation**: `--obo_id` must contain a colon separating non-empty prefix and local identifier segments (or underscore-separated `PREFIX_ID` normalized automatically). `--iri` must start with `http://` or `https://`.
2. **Relation Validation**: Values passed to `--relations` must belong to the supported set (`parents`, `children`, `ancestors`, `descendants`, `hierarchicalParents`, `hierarchicalChildren`, `hierarchicalAncestors`, `hierarchicalDescendants`, `graph`). Unsupported relation names raise a descriptive `ValueError`.
3. **Rate Limit Enforcement**: `ols_utils.make_request` tracks the monotonic timestamp of the last outgoing HTTP request and sleeps for the remaining interval whenever elapsed time is less than `0.2` seconds (`5.0` QPS maximum).
4. **JSON Schema Integrity**: Output from `visualize_hierarchy.py` must conform to the schema documented in `references/dashboard_schema.md` and `assets/dashboard_schema.json` (`source`, `target_term`, `nodes`, `edges`, `trees`, `root_paths`, `metrics`, `input_summary`, `processing_summary`).

### 4.4 Outputs

| Output File | Producer | Format | Contents |
| :--- | :--- | :--- | :--- |
| `term.json` | `get_term.py` / `run_pipeline.py` | UTF-8 JSON | Raw OLS4 term metadata combined with requested hierarchical relation payloads. |
| `hierarchy_graph.json` | `visualize_hierarchy.py` / `run_pipeline.py` | UTF-8 JSON | Normalized `nodes`, typed `edges`, `trees` forest, `root_paths`, `input_summary`, `processing_summary`, and graph `metrics`. |
| `ontology_profile.json` | `visualize_ontology.py` / `run_pipeline.py` | UTF-8 JSON | Normalized ontology summary KPIs, root terms, and global OLS4 repository statistics. |
| `dashboard.html` | `generate_dashboard.py` / `run_pipeline.py` | Self-Contained HTML5 | Interactive web dashboard following `DESIGN.md` with 3D Structural Data Diagram, 2D Interactive Relationship Node Map, Lineage Tree, Data Pipeline inspector, Corpus Metrics & Heatmap, Light/Dark/System theme selector, term inspector, citations, and disclaimer. |
| Console Summary | `run_pipeline.py`, `get_term.py` | Plaintext stdout | Structured summary reporting term label, OBO ID, ontology, ancestor/child counts, citations, disclaimer, and relative output file paths. |

---

## 5. Non-Functional Requirements

### 5.1 Performance & Latency
- **Rate Limiting**: Outgoing live HTTP calls must never exceed 5.0 requests per second (`RATE_LIMIT_DELAY = 0.2` seconds).
- **Resilience & Retries**: Transient HTTP `429 Too Many Requests`, `500`, `502`, `503`, and `504` responses must trigger exponential backoff retries (up to 3 attempts, base delay `1.0s`, multiplier `2.0x`).
- **Test Suite Speed**: The offline test suite (transport patched with recorded responses) must complete in under 5 seconds on standard workstation hardware.
- **Client Rendering**: `dashboard.html` must initialize and render graphs of up to 500 nodes and 1,000 edges smoothly in standard HTML5 browsers and embedded webviews.
- **Label Legibility**: At every zoom level, visible node labels in the 3D, 2D, and tree views must not overlap each other or other nodes; label placement is recomputed at most once per animation frame during zoom and pan.

### 5.2 Security & Environment Independence
- **Relative Path Resolution**: All internal file lookups (`sample_data/`, `references/`, `assets/`, and `.licenses/`) use `pathlib.Path` relative to the project root or user-specified relative output arguments.
- **Safe HTML/JS Serialization**: Inline JSON injected into `dashboard.html` escapes `</script>` sequences (`<\/script>`) and HTML-sensitive characters in DOM attributes to prevent Cross-Site Scripting (XSS) from untrusted ontology annotation strings.
- **Standard Library Runtime**: Relies strictly on Python >= 3.10 standard library (`urllib`, `json`, `argparse`, `pathlib`, `time`, `logging`) with optional support for `polite-http`.

### 5.3 Healthcare & Life Sciences (HCLS) Compliance
- **Zero PHI/PII Mandate**: All example data, test fixtures, and generated outputs contain exclusively public biomedical ontology concepts (e.g., cellular components, disease classifications). No patient records, clinical identifiers, or personally identifiable information are processed or stored.
- **Scientific & Clinical Disclaimer**: Every CLI summary and `dashboard.html` file displays the mandatory disclaimer stating that ontology classifications, hierarchical structures, and cross-references reflect curated biomedical models and automated inferences from participating consortiums, and must be independently verified for clinical diagnostic or medical treatment decisions.
- **Attribution & Licensing**: Upholds Apache License 2.0 across all source files, preserves upstream ontology license metadata (e.g., CC BY 4.0, CC0), enforces the `.licenses/` verification guard, and cites McLaughlin et al. (2025) and Jupp et al. (2015).

---

## 6. Error Handling & Edge Cases

| Edge Case / Failure Mode | Detection Mechanism | System Behavior & Recovery Strategy | Exit Code |
| :--- | :--- | :--- | :--- |
| **Missing `.licenses/` Guard File** | `verify_license_guard()` checks workspace root before API/pipeline execution. | Logs the EMBL-EBI OLS Terms of Use notice to stderr/stdout, creates `.licenses/embl_ebi_ols_visualize_LICENSE.txt` with current UTC ISO timestamp, and continues execution. | `0` |
| **Malformed OBO ID (e.g., `"GO0005634"` without colon)** | Regex/delimiter check in `obo_id_to_iri()` and `resolve_ontology()`. | If underscore-delimited (`GO_0005634`), normalizes to `GO:0005634`; otherwise raises `ValueError` with a clear message explaining expected `PREFIX:ID` syntax. | `2` / `1` |
| **Unknown OBO Prefix without `--ontology`** | Prefix lookup in `OBO_PREFIX_TO_ONTOLOGY`. | Falls back to the lowercase prefix string (e.g., `UBERON:0000955` -> `uberon`) and logs an informational message; if prefix cannot be extracted and `--ontology` is omitted, exits with a descriptive error. | `1` |
| **Empty Search Results for `--query`** | `search_ols.py` / `run_pipeline.py` checks `response.docs` length. | If `--exact` returns 0 hits in `run_pipeline.py`, retries automatically with non-exact search; if still 0 hits, writes an empty/diagnostic summary and exits with an informative error message. | `1` |
| **Multiple Inheritance (Diamond DAGs)** | `visualize_hierarchy.py` tracks ancestor/child edges per path during tree construction. | Preserves full multi-parent connections in the `nodes`/`edges` DAG structure and clones shared child nodes along distinct parent branches (bounded by max depth and visited-on-path cycle detection) for the collapsible tree view. The tree opens with only the deepest occurrence of the term expanded; other branches start collapsed. | `0` |
| **Dense Graphs (many siblings or long labels)** | Label placement in the dashboard. | Lower-priority labels are hidden until zooming in frees space; hovering a node shows its full label and definition in a tooltip. | `0` |
| **Cyclic Relations in Non-Strict Ontologies** | Path-level `visited` set during DFS tree construction and BFS depth assignment. | Terminates recursive expansion on the back-edge, preventing infinite recursion while retaining the edge in the node-link graph representation. | `0` |
| **Deprecated / Obsolete Term Queried** | Checks `is_obsolete: true` in term JSON. | Renders an `Obsolete` status indicator (`#E11D48`) in the dashboard header and inspector panel, and displays `term_replaced_by` or `consider` annotations if present. | `0` |
| **HTTP 429 / 503 Transient API Errors** | HTTP status code inspection in `ols_utils.make_request()`. | Applies exponential backoff (`1s`, `2s`, `4s`) honoring `Retry-After` headers when provided; raises `RuntimeError` with status and URL context if retries are exhausted. | `1` |
| **Network Unreachable** | `URLError` / timeout in `ols_utils.make_request()`. | Retries with backoff, then raises `RuntimeError` asking the user to check network access. No substitute or cached data is shown. | `1` |
| **Unknown Term / HTTP 404** | HTTP status in `ols_utils.make_request()`. | Raises `RuntimeError` with the URL; no other term is substituted. | `1` |
| **Ancestors Without Connecting Edges** | `visualize_hierarchy.py` finds fetched terms that no OLS4 edge connects. | Leaves them out of the graph and reports the count in `processing_summary.unconnected_nodes`; no lineage is inferred. | `0` |
| **Missing Metadata (license, version, synonym scope, relation type)** | Field absent from the OLS4 response or uploaded file. | Field is left empty and the corresponding dashboard row/badge is hidden; untyped hierarchical links are labelled `hierarchical`. | `0` |
| **Corrupted or Missing Input JSON File** | `FileNotFoundError` or `json.JSONDecodeError` in visualizer/dashboard scripts. | Catches exception, logs structured error message identifying the offending file path and parse failure details, and exits cleanly without writing partial output files. | `1` |
| **Missing Optional `polite-http` Package** | `ImportError` guard in `scripts/ols_utils.py`. | Transparently falls back to Python standard library `urllib.request` with built-in monotonic rate limiting and retry logic. | `0` |
