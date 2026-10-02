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
"""CLI and programmatic wrapper for EMBL-EBI OLS4 ontology metadata endpoints."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position


def get_ontology(
    ontology: str | None = None,
    list_all: bool = False,
    include_roots: bool = True,
    page: int = 0,
    size: int = 20,
    mock: bool = False,
) -> dict[str, Any]:
  """Fetches metadata for a specific ontology or lists indexed ontologies.

  Args:
    ontology: Ontology slug (e.g., `go`, `doid`, `hp`).
    list_all: If True, fetches a paginated list of ontologies from `/ontologies`.
    include_roots: If True and `ontology` is specified, attaches root terms under `roots`.
    page: Zero-based page index when `list_all=True`.
    size: Page size when `list_all=True`.
    mock: If True, returns local synthetic mock data.

  Returns:
    Ontology metadata dictionary.
  """
  if list_all or not ontology:
    if not list_all and not ontology:
      raise ValueError("Specify either --ontology <slug> or --list.")
    return ols_utils.make_request(
        f"{ols_utils.BASE_URL}/ontologies",
        params={"page": page, "size": size},
        mock=mock,
    )

  slug = ontology.strip().lower()
  onto_data = ols_utils.make_request(
      f"{ols_utils.BASE_URL}/ontologies/{slug}",
      mock=mock,
  )

  if include_roots and "roots" not in onto_data:
    roots_resp = ols_utils.make_request(
        f"{ols_utils.BASE_URL}/ontologies/{slug}/terms/roots",
        mock=mock,
    )
    onto_data["roots"] = ols_utils.extract_embedded_list(roots_resp, "terms")

  return onto_data


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `get_ontology.py`."""
  parser = argparse.ArgumentParser(
      description="Retrieve ontology metadata and root terms from EMBL-EBI OLS4."
  )
  parser.add_argument(
      "--ontology",
      help="Ontology slug (e.g., go, doid, hp, mondo, chebi).",
  )
  parser.add_argument(
      "--list",
      dest="list_all",
      action="store_true",
      help="List indexed ontologies with pagination.",
  )
  parser.add_argument(
      "--no_roots",
      action="store_true",
      help="Skip fetching root terms when retrieving a single ontology.",
  )
  parser.add_argument(
      "--page",
      type=int,
      default=0,
      help="Page number when --list is specified (default: 0).",
  )
  parser.add_argument(
      "--size",
      type=int,
      default=20,
      help="Page size when --list is specified (default: 20).",
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
  """CLI entrypoint for `get_ontology.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    result = get_ontology(
        ontology=args.ontology,
        list_all=args.list_all,
        include_roots=not args.no_roots,
        page=args.page,
        size=args.size,
        mock=args.mock,
    )
    out_path = ols_utils.write_json_output(result, args.output)
    print(f"Ontology metadata saved to {out_path}.")
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("get_ontology failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
