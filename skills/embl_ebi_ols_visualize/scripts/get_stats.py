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
"""CLI and programmatic wrapper for the EMBL-EBI OLS4 `/v2/stats` endpoint."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position


def get_stats() -> dict[str, Any]:
  """Fetches global OLS4 repository statistics from `/v2/stats`.

  Args:

  Returns:
    Dictionary containing global ontology, class, property, and individual counts.
  """
  return ols_utils.make_request(
      f"{ols_utils.BASE_URL}/v2/stats",
  )


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `get_stats.py`."""
  parser = argparse.ArgumentParser(
      description="Retrieve global repository statistics from EMBL-EBI OLS4 (/v2/stats)."
  )
  parser.add_argument(
      "-o",
      "--output",
      required=True,
      help="Output JSON file path.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `get_stats.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    result = get_stats()
    out_path = ols_utils.write_json_output(result, args.output)
    num_ontologies = result.get("numberOfOntologies", 0)
    num_classes = result.get("numberOfClasses", 0)
    print(
        f"OLS4 repository statistics ({num_ontologies} ontologies, "
        f"{num_classes} classes) saved to {out_path}."
    )
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("get_stats failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
