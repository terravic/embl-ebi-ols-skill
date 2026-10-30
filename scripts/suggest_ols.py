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
"""CLI and programmatic wrapper for the EMBL-EBI OLS4 `/suggest` endpoint."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position


def suggest_ols(
    query: str,
    ontology: str | None = None,
    rows: int = 10,
    start: int = 0,
) -> dict[str, Any]:
  """Queries the OLS4 `/suggest` autocomplete endpoint.

  Args:
    query: Prefix string to autocomplete.
    ontology: Optional ontology filter slug.
    rows: Number of suggestions to return.
    start: Pagination offset.

  Returns:
    OLS4 suggestion response dictionary.
  """
  if not query or not query.strip():
    raise ValueError("Autocomplete query (--query) must be a non-empty string.")
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

  return ols_utils.make_request(
      f"{ols_utils.BASE_URL}/suggest",
      params=params,
  )


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI parser for `suggest_ols.py`."""
  parser = argparse.ArgumentParser(
      description="Fetch prefix autocomplete suggestions from EMBL-EBI OLS4."
  )
  parser.add_argument(
      "-q", "--query", required=True, help="Prefix string to autocomplete."
  )
  parser.add_argument(
      "--ontology",
      help="Optional ontology slug filter (e.g., go, doid, hp).",
  )
  parser.add_argument(
      "--rows",
      type=int,
      default=10,
      help="Maximum number of suggestions to return (default: 10).",
  )
  parser.add_argument(
      "--start",
      type=int,
      default=0,
      help="Pagination offset (default: 0).",
  )
  parser.add_argument(
      "-o",
      "--output",
      required=True,
      help="Output JSON file path.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `suggest_ols.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    result = suggest_ols(
        query=args.query,
        ontology=args.ontology,
        rows=args.rows,
        start=args.start,
    )
    out_path = ols_utils.write_json_output(result, args.output)
    docs = result.get("response", {}).get("docs", [])
    print(
        f"Autocomplete completed for prefix='{args.query}': "
        f"{len(docs)} suggestion(s) saved to {out_path}."
    )
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("suggest_ols failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
