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
"""CLI and programmatic wrapper for the EMBL-EBI OLS4 `/search` endpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position


def _normalize_parent_filter(val: str | None) -> str | None:
  """Converts an OBO ID or IRI filter value into a canonical IRI string."""
  if not val or not val.strip():
    return None
  items = [item.strip() for item in val.split(",") if item.strip()]
  converted = [ols_utils.obo_id_to_iri(item) for item in items]
  return ",".join(converted)


def search_ols(
    query: str,
    ontology: str | None = None,
    entity_type: str | None = None,
    exact: bool = False,
    defining: bool = False,
    obsolete: bool = False,
    local: bool = False,
    children_of: str | None = None,
    all_children_of: str | None = None,
    rows: int = 10,
    start: int = 0,
    mock: bool = False,
) -> dict[str, Any]:
  """Executes a full-text search against the OLS4 `/search` endpoint.

  Args:
    query: Search keyword or phrase.
    ontology: Optional ontology slug (e.g., `go`, `doid`).
    entity_type: Optional entity type (`class`, `property`, `individual`, `ontology`).
    exact: If True, restricts to exact matches.
    defining: If True, restricts to terms from their defining ontology.
    obsolete: If True, includes obsolete/deprecated terms.
    local: If True, restricts to locally defined terms.
    children_of: Optional OBO ID or IRI restricting results to direct/subclass children.
    all_children_of: Optional OBO ID or IRI restricting results across hierarchical relations.
    rows: Maximum number of results to return.
    start: Zero-based pagination offset.
    mock: If True, returns synthetic offline search fixtures.

  Returns:
    OLS4 search response dictionary.
  """
  if not query or not query.strip():
    raise ValueError("Search query (--query) must be a non-empty string.")
  if rows < 1:
    raise ValueError("--rows must be >= 1.")
  if start < 0:
    raise ValueError("--start must be >= 0.")

  params: dict[str, Any] = {
      "q": query.strip(),
      "rows": rows,
      "start": start,
  }
  if ontology:
    params["ontology"] = ontology.strip().lower()
  if entity_type:
    params["type"] = entity_type.strip().lower()
  if exact:
    params["exact"] = True
  if defining:
    params["isDefiningOntology"] = True
  if obsolete:
    params["obsoletes"] = True
  if local:
    params["local"] = True
  if children_of:
    params["childrenOf"] = _normalize_parent_filter(children_of)
  if all_children_of:
    params["allChildrenOf"] = _normalize_parent_filter(all_children_of)

  return ols_utils.make_request(
      f"{ols_utils.BASE_URL}/search",
      params=params,
      mock=mock,
  )


def build_parser() -> argparse.ArgumentParser:
  """Builds the argument parser for `search_ols.py`."""
  parser = argparse.ArgumentParser(
      description="Search biomedical ontology terms across EMBL-EBI OLS4."
  )
  parser.add_argument(
      "-q", "--query", required=True, help="Search keyword or phrase."
  )
  parser.add_argument(
      "--ontology",
      help="Filter by ontology slug (e.g., go, doid, hp, mondo, chebi).",
  )
  parser.add_argument(
      "--type",
      dest="entity_type",
      choices=["class", "property", "individual", "ontology"],
      help="Filter by entity type.",
  )
  parser.add_argument(
      "--exact",
      action="store_true",
      help="Require exact match on term label or synonym.",
  )
  parser.add_argument(
      "--defining",
      action="store_true",
      help="Restrict to terms in their defining ontology (isDefiningOntology=true).",
  )
  parser.add_argument(
      "--obsolete",
      action="store_true",
      help="Include obsolete/deprecated ontology terms.",
  )
  parser.add_argument(
      "--local",
      action="store_true",
      help="Restrict to locally defined terms.",
  )
  parser.add_argument(
      "--childrenOf",
      dest="children_of",
      help="Restrict results to subclass children of the given OBO ID or IRI.",
  )
  parser.add_argument(
      "--allChildrenOf",
      dest="all_children_of",
      help="Restrict results to hierarchical children (including part_of) of OBO ID or IRI.",
  )
  parser.add_argument(
      "--rows",
      type=int,
      default=10,
      help="Number of search results to return (default: 10).",
  )
  parser.add_argument(
      "--start",
      type=int,
      default=0,
      help="Pagination start offset (default: 0).",
  )
  parser.add_argument(
      "-o",
      "--output",
      required=True,
      help="Output JSON file path.",
  )
  parser.add_argument(
      "--mock",
      action="store_true",
      help="Use local synthetic mock data from sample_data/ without network calls.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `search_ols.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    result = search_ols(
        query=args.query,
        ontology=args.ontology,
        entity_type=args.entity_type,
        exact=args.exact,
        defining=args.defining,
        obsolete=args.obsolete,
        local=args.local,
        children_of=args.children_of,
        all_children_of=args.all_children_of,
        rows=args.rows,
        start=args.start,
        mock=args.mock,
    )
    out_path = ols_utils.write_json_output(result, args.output)
    docs = result.get("response", {}).get("docs", [])
    num_found = result.get("response", {}).get("numFound", len(docs))
    print(
        f"Search completed for query='{args.query}': {num_found} total match(es), "
        f"{len(docs)} returned. Saved to {out_path}."
    )
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("search_ols failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
