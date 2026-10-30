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
"""CLI and programmatic wrapper for EMBL-EBI OLS4 term and relation lookups."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position


def parse_relations_arg(relations: str | list[str] | None) -> list[str]:
  """Parses and validates a comma-separated string or list of term relations."""
  if not relations:
    return []
  if isinstance(relations, str):
    items = [item.strip() for item in relations.split(",") if item.strip()]
  else:
    items = [str(item).strip() for item in relations if str(item).strip()]

  invalid = [r for r in items if r not in ols_utils.VALID_TERM_RELATIONS]
  if invalid:
    raise ValueError(
        f"Unsupported relation(s): {', '.join(invalid)}. "
        f"Supported values: {', '.join(ols_utils.VALID_TERM_RELATIONS)}"
    )
  return items


def get_term(
    obo_id: str | None = None,
    iri: str | None = None,
    ontology: str | None = None,
    relations: str | list[str] | None = None,
    roots: bool = False,
    preferred_roots: bool = False,
    lineage: bool = False,
) -> dict[str, Any]:
  """Retrieves term metadata, root terms, and hierarchical relation blocks.

  Args:
    obo_id: OBO identifier (e.g., `GO:0005634`, `DOID:9351`).
    iri: Full resource IRI.
    ontology: Ontology slug (e.g., `go`, `doid`). Resolved from `obo_id` if omitted.
    relations: Optional list or comma-separated string of relation endpoints.
    roots: If True, fetches ontology root terms instead of a single term.
    preferred_roots: If True, fetches ontology preferred root terms.
    lineage: If True, also fetches the parents of every ancestor so the full
      root-to-term lineage is connected by real OLS4 edges.

  Returns:
    Dictionary containing term details and a `relations` block.
  """
  if roots or preferred_roots:
    if not ontology and not obo_id:
      raise ValueError("--ontology is required when --roots or --preferred_roots is set.")
    onto_slug = ols_utils.resolve_ontology(obo_id, ontology)
    sub_endpoint = "preferredRoots" if preferred_roots else "roots"
    url = f"{ols_utils.BASE_URL}/ontologies/{onto_slug}/terms/{sub_endpoint}"
    return ols_utils.make_request(url)

  if not obo_id and not iri:
    raise ValueError("Provide either --obo_id or --iri to fetch a term.")

  target_iri = iri.strip() if iri else ols_utils.obo_id_to_iri(str(obo_id))
  onto_slug = ols_utils.resolve_ontology(obo_id or target_iri, ontology)
  encoded_iri = ols_utils.double_encode_iri(target_iri)
  base_term_url = f"{ols_utils.BASE_URL}/ontologies/{onto_slug}/terms/{encoded_iri}"

  term_data = ols_utils.make_request(base_term_url)
  existing_relations = term_data.get("relations", {})
  if not isinstance(existing_relations, dict):
    existing_relations = {}

  requested_rels = parse_relations_arg(relations)
  if requested_rels:
    fetched_relations: dict[str, Any] = {}
    for rel in requested_rels:
      rel_url = f"{base_term_url}/{rel}"
      rel_resp = ols_utils.make_request(rel_url)
      if rel == "graph":
        fetched_relations[rel] = rel_resp
      else:
        fetched_relations[rel] = ols_utils.extract_embedded_list(
            rel_resp, "terms"
        )
    term_data["relations"] = fetched_relations
  else:
    term_data["relations"] = existing_relations

  if lineage:
    term_data["relations"]["lineage"] = fetch_ancestor_lineage(
        term_data["relations"], onto_slug
    )

  return term_data


def fetch_ancestor_lineage(
    relations: dict[str, Any], onto_slug: str
) -> list[dict[str, Any]]:
  """Fetches `/parents` and `/hierarchicalParents` for every ancestor.

  This yields the real edges between ancestors, so the full root-to-term
  lineage can be drawn without inferring any links.

  Args:
    relations: Relation block already fetched for the target term.
    onto_slug: Ontology slug used to address the ancestor terms.

  Returns:
    List of `{iri, obo_id, parents, hierarchicalParents}` records.
  """
  seen: set[str] = set()
  lineage: list[dict[str, Any]] = []
  for key in ("ancestors", "hierarchicalAncestors"):
    for anc in relations.get(key) or []:
      if not isinstance(anc, dict):
        continue
      anc_iri = str(anc.get("iri") or "").strip()
      if not anc_iri or anc_iri in seen:
        continue
      seen.add(anc_iri)
      anc_url = (
          f"{ols_utils.BASE_URL}/ontologies/{onto_slug}/terms/"
          f"{ols_utils.double_encode_iri(anc_iri)}"
      )
      record: dict[str, Any] = {"iri": anc_iri, "obo_id": anc.get("obo_id")}
      for rel in ("parents", "hierarchicalParents"):
        resp = ols_utils.make_request(f"{anc_url}/{rel}")
        record[rel] = ols_utils.extract_embedded_list(resp, "terms")
      lineage.append(record)
  return lineage


def format_term_summary(term_data: dict[str, Any]) -> str:
  """Formats a concise human-readable summary of a term payload."""
  label = term_data.get("label", "Unknown")
  obo_id = term_data.get("obo_id") or ols_utils.iri_to_obo_id(
      str(term_data.get("iri", ""))
  )
  ontology = term_data.get("ontology_name", "unknown")
  descriptions = term_data.get("description") or []
  definition = descriptions[0] if descriptions else "No definition available."
  rels = term_data.get("relations") or {}
  parents = rels.get("parents") or rels.get("hierarchicalParents") or []
  children = rels.get("children") or rels.get("hierarchicalChildren") or []
  ancestors = rels.get("ancestors") or rels.get("hierarchicalAncestors") or []

  lines = [
      f"Term: {label} ({obo_id})",
      f"Ontology: {ontology} | IRI: {term_data.get('iri', 'N/A')}",
      f"Obsolete: {bool(term_data.get('is_obsolete', False))}",
      f"Definition: {definition}",
      (
          f"Relations: {len(parents)} direct parent(s), "
          f"{len(children)} direct child(ren), "
          f"{len(ancestors)} ancestor(s)"
      ),
      f"Citation: {ols_utils.PRIMARY_CITATION}",
      f"Disclaimer: {ols_utils.SCIENTIFIC_DISCLAIMER}",
  ]
  return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `get_term.py`."""
  parser = argparse.ArgumentParser(
      description="Retrieve ontology term details and hierarchical relations from EMBL-EBI OLS4."
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
      "--ontology",
      help="Ontology slug (e.g., go, doid, hp). Inferred from --obo_id if omitted.",
  )
  parser.add_argument(
      "--relations",
      help=(
          "Comma-separated hierarchical relations to fetch: "
          + ",".join(ols_utils.VALID_TERM_RELATIONS)
      ),
  )
  parser.add_argument(
      "--roots",
      action="store_true",
      help="Fetch root terms for the specified ontology.",
  )
  parser.add_argument(
      "--preferred_roots",
      action="store_true",
      help="Fetch preferred root terms for the specified ontology.",
  )
  parser.add_argument(
      "--lineage",
      action="store_true",
      help="Also fetch each ancestor's parents to connect the full lineage.",
  )
  parser.add_argument(
      "--summary",
      action="store_true",
      help="Print a detailed human-readable summary to stdout.",
  )
  parser.add_argument(
      "-o",
      "--output",
      required=True,
      help="Output JSON file path.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `get_term.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    data = get_term(
        obo_id=args.obo_id,
        iri=args.iri,
        ontology=args.ontology,
        relations=args.relations,
        roots=args.roots,
        preferred_roots=args.preferred_roots,
        lineage=args.lineage,
    )
    out_path = ols_utils.write_json_output(data, args.output)
    if args.summary and not (args.roots or args.preferred_roots):
      print(format_term_summary(data))
    print(f"Term payload saved to {out_path}.")
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("get_term failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
