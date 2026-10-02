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
"""CLI and programmatic wrapper for EMBL-EBI OLS4 individual endpoints."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position

VALID_INDIVIDUAL_RELATIONS = ("types", "alltypes", "jstree")


def get_individual(
    obo_id: str | None = None,
    iri: str | None = None,
    ontology: str | None = None,
    relations: str | list[str] | None = None,
    mock: bool = False,
) -> dict[str, Any]:
  """Retrieves ontology individual instance metadata and class type relations.

  Args:
    obo_id: OBO identifier for the individual.
    iri: Full canonical IRI for the individual.
    ontology: Ontology slug.
    relations: Optional comma-separated individual relations (`types`, `alltypes`, `jstree`).
    mock: If True, uses local synthetic mock data.

  Returns:
    Individual metadata dictionary with optional `relations` block.
  """
  if not obo_id and not iri:
    raise ValueError("Provide either --obo_id or --iri to fetch an individual.")

  target_iri = iri.strip() if iri else ols_utils.obo_id_to_iri(str(obo_id))
  onto_slug = ols_utils.resolve_ontology(obo_id or target_iri, ontology)
  encoded_iri = ols_utils.double_encode_iri(target_iri)
  base_url = f"{ols_utils.BASE_URL}/ontologies/{onto_slug}/individuals/{encoded_iri}"

  ind_data = ols_utils.make_request(base_url, mock=mock)

  if relations:
    rel_list = (
        [r.strip() for r in relations.split(",") if r.strip()]
        if isinstance(relations, str)
        else [str(r).strip() for r in relations if str(r).strip()]
    )
    invalid = [r for r in rel_list if r not in VALID_INDIVIDUAL_RELATIONS]
    if invalid:
      raise ValueError(
          f"Invalid individual relation(s): {', '.join(invalid)}. "
          f"Supported: {', '.join(VALID_INDIVIDUAL_RELATIONS)}"
      )
    rel_block: dict[str, Any] = {}
    for rel in rel_list:
      rel_resp = ols_utils.make_request(f"{base_url}/{rel}", mock=mock)
      rel_block[rel] = ols_utils.extract_embedded_list(rel_resp, "terms")
    ind_data["relations"] = rel_block

  return ind_data


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `get_individual.py`."""
  parser = argparse.ArgumentParser(
      description="Retrieve ontology individual metadata and class types from EMBL-EBI OLS4."
  )
  parser.add_argument(
      "--obo_id",
      help="OBO identifier for the individual.",
  )
  parser.add_argument(
      "--iri",
      help="Full canonical IRI of the individual.",
  )
  parser.add_argument(
      "--ontology",
      help="Ontology slug (e.g., ro, go, obi).",
  )
  parser.add_argument(
      "--relations",
      help="Comma-separated individual relations: types,alltypes,jstree.",
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
      help="Use local synthetic mock data without network calls.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `get_individual.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    result = get_individual(
        obo_id=args.obo_id,
        iri=args.iri,
        ontology=args.ontology,
        relations=args.relations,
        mock=args.mock,
    )
    out_path = ols_utils.write_json_output(result, args.output)
    print(f"Individual payload saved to {out_path}.")
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("get_individual failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
