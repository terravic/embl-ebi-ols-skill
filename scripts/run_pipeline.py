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
"""Unified end-to-end pipeline orchestrator for the `embl-ebi-ols-visualize` skill."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import generate_dashboard  # pylint: disable=wrong-import-position
import get_ontology  # pylint: disable=wrong-import-position
import get_stats  # pylint: disable=wrong-import-position
import get_term  # pylint: disable=wrong-import-position
import ols_utils  # pylint: disable=wrong-import-position
import search_ols  # pylint: disable=wrong-import-position
import visualize_hierarchy  # pylint: disable=wrong-import-position
import visualize_ontology  # pylint: disable=wrong-import-position

DEFAULT_PIPELINE_RELATIONS = (
    "parents,children,ancestors,hierarchicalParents,hierarchicalChildren,"
    "hierarchicalAncestors,graph"
)


def resolve_query_to_entity(
    query: str,
    ontology: str | None = None,
) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
  """Resolves a search keyword to `(obo_id, iri, ontology_slug, search_payload)`."""
  exact_res = search_ols.search_ols(
      query=query,
      ontology=ontology,
      entity_type="class",
      exact=True,
      defining=True,
      rows=10,
  )
  docs = exact_res.get("response", {}).get("docs", [])
  search_payload = exact_res

  if not docs:
    broad_res = search_ols.search_ols(
        query=query,
        ontology=ontology,
        entity_type="class",
        exact=False,
        defining=False,
        rows=10,
    )
    docs = broad_res.get("response", {}).get("docs", [])
    search_payload = broad_res

  if not docs:
    raise LookupError(
        f"No ontology terms found matching query='{query}'"
        + (f" in ontology='{ontology}'." if ontology else ".")
    )

  # Prefer defining ontology docs when available
  defining_docs = [d for d in docs if d.get("is_defining_ontology")]
  top_doc = defining_docs[0] if defining_docs else docs[0]
  resolved_obo_id = top_doc.get("obo_id") or ols_utils.iri_to_obo_id(
      str(top_doc.get("iri") or "")
  )
  resolved_iri = top_doc.get("iri")
  resolved_ontology = top_doc.get("ontology_name") or ontology
  return resolved_obo_id, resolved_iri, resolved_ontology, search_payload


def run_pipeline(
    output_dir: str | Path,
    obo_id: str | None = None,
    iri: str | None = None,
    query: str | None = None,
    ontology: str | None = None,
    relations: str = DEFAULT_PIPELINE_RELATIONS,
    include_stats: bool = False,
) -> dict[str, Any]:
  """Executes the complete OLS4 lookup, hierarchy compilation, and dashboard pipeline.

  Args:
    output_dir: Directory where JSON artifacts and `dashboard.html` will be saved.
    obo_id: Optional OBO-style identifier (`GO:0005634`, `DOID:9351`).
    iri: Optional full canonical IRI.
    query: Optional keyword string for automatic entity resolution.
    ontology: Optional ontology slug (`go`, `doid`, `hp`).
    relations: Comma-separated hierarchical relations to fetch.
    include_stats: If True, fetches ontology metadata and global `/v2/stats`.

  Returns:
    Dictionary summarizing generated paths and metrics.
  """
  if not any([obo_id, iri, query, ontology, include_stats]):
    raise ValueError(
        "Provide at least one of --obo_id, --iri, --query, --ontology, or --stats."
    )

  license_guard_path = ols_utils.verify_license_guard()
  out_dir = Path(output_dir)
  out_dir.mkdir(parents=True, exist_ok=True)

  resolved_obo_id = obo_id
  resolved_iri = iri
  resolved_ontology = ontology
  search_json_path: Path | None = None

  # Step 1: Resolve keyword query if `--query` was supplied without `--obo_id` / `--iri`
  if query and not (resolved_obo_id or resolved_iri):
    (
        resolved_obo_id,
        resolved_iri,
        resolved_ontology,
        search_payload,
    ) = resolve_query_to_entity(query=query, ontology=ontology)
    search_json_path = ols_utils.write_json_output(
        search_payload, out_dir / "search_results.json"
    )

  term_json_path: Path | None = None
  hierarchy_json_path: Path | None = None
  hierarchy_payload: dict[str, Any] | None = None

  # Step 2: Fetch term and requested relations if a term identifier is available
  if resolved_obo_id or resolved_iri:
    term_data = get_term.get_term(
        obo_id=resolved_obo_id,
        iri=resolved_iri,
        ontology=resolved_ontology,
        relations=relations,
        lineage=True,
    )
    term_json_path = ols_utils.write_json_output(
        term_data, out_dir / "term.json"
    )
    if not resolved_ontology:
      resolved_ontology = str(term_data.get("ontology_name") or "").lower() or None

    hierarchy_payload = visualize_hierarchy.build_hierarchy_payload(term_data)
    hierarchy_json_path = ols_utils.write_json_output(
        hierarchy_payload, out_dir / "hierarchy_graph.json"
    )

  # Step 3: Fetch ontology metadata and global repository statistics if requested
  # or if running an ontology-level overview without a specific term.
  ontology_json_path: Path | None = None
  stats_json_path: Path | None = None
  ontology_profile_path: Path | None = None
  onto_data: dict[str, Any] | None = None
  stats_data: dict[str, Any] | None = None

  should_fetch_ontology = bool(
      include_stats or (resolved_ontology and not (resolved_obo_id or resolved_iri))
  )
  if should_fetch_ontology and resolved_ontology:
    onto_data = get_ontology.get_ontology(
        ontology=resolved_ontology, include_roots=True
    )
    ontology_json_path = ols_utils.write_json_output(
        onto_data, out_dir / "ontology.json"
    )

  if include_stats or not (resolved_obo_id or resolved_iri):
    stats_data = get_stats.get_stats()
    stats_json_path = ols_utils.write_json_output(
        stats_data, out_dir / "stats.json"
    )

  if onto_data or stats_data:
    onto_profile_payload = visualize_ontology.build_ontology_visualization_payload(
        ontology_data=onto_data,
        stats_data=stats_data,
    )
    ontology_profile_path = ols_utils.write_json_output(
        onto_profile_payload, out_dir / "ontology_profile.json"
    )

  # Step 4: Generate standalone HTML5 interactive dashboard
  dashboard_path = generate_dashboard.generate_dashboard(
      output_path=out_dir / "dashboard.html",
      term_json_path=term_json_path,
      graph_json_path=hierarchy_json_path,
      ontology_json_path=ontology_json_path,
      stats_json_path=stats_json_path,
  )

  return {
      "license_guard": str(license_guard_path),
      "output_dir": str(out_dir),
      "search_json": str(search_json_path) if search_json_path else None,
      "term_json": str(term_json_path) if term_json_path else None,
      "hierarchy_json": str(hierarchy_json_path) if hierarchy_json_path else None,
      "ontology_json": str(ontology_json_path) if ontology_json_path else None,
      "stats_json": str(stats_json_path) if stats_json_path else None,
      "ontology_profile_json": (
          str(ontology_profile_path) if ontology_profile_path else None
      ),
      "dashboard_html": str(dashboard_path),
      "hierarchy_payload": hierarchy_payload,
      "ontology_data": onto_data,
      "stats_data": stats_data,
  }


def format_pipeline_summary(result: dict[str, Any]) -> str:
  """Formats the terminal summary for `run_pipeline.py`."""
  lines = [
      "========================================================================",
      "EMBL-EBI OLS Visualize Skill (embl-ebi-ols-visualize) Pipeline Summary",
      "========================================================================",
  ]
  h_payload = result.get("hierarchy_payload")
  if isinstance(h_payload, dict):
    target = h_payload.get("target_term", {})
    metrics = h_payload.get("metrics", {})
    lines.extend([
        f"Target Term      : {target.get('label', 'N/A')} ({target.get('id', 'N/A')})",
        f"Defining Ontology: {target.get('ontology_prefix', 'N/A')} ({target.get('ontology', 'N/A')})",
        f"Canonical IRI    : {target.get('iri', 'N/A')}",
        f"Graph Metrics    : {metrics.get('node_count', 0)} nodes, {metrics.get('edge_count', 0)} semantic edges",
        (
            f"Lineage Counts   : {metrics.get('ancestor_count', 0)} ancestors, "
            f"{metrics.get('direct_parent_count', 0)} direct parents, "
            f"{metrics.get('direct_child_count', 0)} direct/partonomic children"
        ),
    ])
  elif result.get("ontology_data"):
    onto = result["ontology_data"]
    lines.extend([
        f"Ontology Profiled: {onto.get('ontologyId', 'N/A')}",
        f"Total Terms      : {onto.get('numberOfTerms', 0)}",
        f"Total Properties : {onto.get('numberOfProperties', 0)}",
    ])

  if result.get("stats_data"):
    st = result["stats_data"]
    lines.append(
        f"Repository Stats : {st.get('numberOfOntologies', 0)} ontologies, "
        f"{st.get('numberOfClasses', 0)} classes indexed"
    )

  lines.extend([
      f"Dashboard HTML   : {result.get('dashboard_html')}",
      "------------------------------------------------------------------------",
      f"Primary Citation : {ols_utils.PRIMARY_CITATION}",
      f"Foundational Ref : {ols_utils.ORIGINAL_CITATION}",
      f"Disclaimer       : {ols_utils.SCIENTIFIC_DISCLAIMER}",
      "========================================================================",
  ])
  return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `run_pipeline.py`."""
  parser = argparse.ArgumentParser(
      description=(
          "Unified end-to-end pipeline for querying EMBL-EBI OLS4 and "
          "generating interactive standalone HTML5 dashboards."
      )
  )
  parser.add_argument(
      "--obo_id",
      help="OBO-style term identifier (e.g., GO:0005634, DOID:9351).",
  )
  parser.add_argument(
      "--iri",
      help="Full canonical IRI of the ontology term.",
  )
  parser.add_argument(
      "-q",
      "--query",
      help="Search keyword for automatic entity resolution (e.g., apoptosis, diabetes).",
  )
  parser.add_argument(
      "--ontology",
      help="Ontology slug (e.g., go, doid, efo, hp, cl, uberon).",
  )
  parser.add_argument(
      "--relations",
      default=DEFAULT_PIPELINE_RELATIONS,
      help=(
          "Comma-separated relations to fetch "
          f"(default: {DEFAULT_PIPELINE_RELATIONS})."
      ),
  )
  parser.add_argument(
      "--stats",
      action="store_true",
      help="Fetch and visualize ontology metadata and global repository statistics.",
  )
  parser.add_argument(
      "-o",
      "--output_dir",
      "--output",
      dest="output_dir",
      required=True,
      help="Output directory to store generated JSON files and dashboard.html.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `run_pipeline.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    result = run_pipeline(
        output_dir=args.output_dir,
        obo_id=args.obo_id,
        iri=args.iri,
        query=args.query,
        ontology=args.ontology,
        relations=args.relations,
        include_stats=args.stats,
    )
    print(format_pipeline_summary(result))
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("run_pipeline failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
