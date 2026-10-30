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
"""Aggregates ontology metadata and OLS4 repository statistics into structured metrics."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position


def profile_ontology(ontology_data: dict[str, Any] | None) -> dict[str, Any] | None:
  """Extracts structured summary metrics from an OLS4 ontology metadata payload."""
  if not ontology_data or not isinstance(ontology_data, dict):
    return None

  config = ontology_data.get("config")
  if not isinstance(config, dict):
    config = {}

  ontology_id = str(
      ontology_data.get("ontologyId") or config.get("namespace") or ""
  ).lower()
  preferred_prefix = str(config.get("preferredPrefix") or "")
  title = str(config.get("title") or "")
  description = str(config.get("description") or "")
  version = str(ontology_data.get("version") or config.get("version") or "")
  loaded = str(ontology_data.get("loaded") or "")
  updated = str(ontology_data.get("updated") or "")
  status = str(ontology_data.get("status") or "")
  homepage = str(config.get("homepage") or "")
  tracker = str(config.get("tracker") or "")

  license_info = config.get("license")
  if isinstance(license_info, dict):
    license_norm = {
        "label": str(license_info.get("label") or ""),
        "url": str(license_info.get("url") or ""),
    }
  else:
    annotations = config.get("annotations")
    lic_urls = (
        annotations.get("license", []) if isinstance(annotations, dict) else []
    )
    license_norm = {
        "label": "",
        "url": str(lic_urls[0]) if lic_urls else "",
    }

  raw_roots = ontology_data.get("roots") or []
  roots_norm: list[dict[str, Any]] = []
  for r in raw_roots:
    if isinstance(r, dict):
      rid = r.get("obo_id") or ols_utils.iri_to_obo_id(str(r.get("iri") or ""))
      descs = r.get("description") or []
      if not rid:
        continue
      roots_norm.append({
          "id": rid,
          "iri": str(r.get("iri") or ""),
          "label": str(r.get("label") or rid),
          "description": str(descs[0]) if descs else "",
      })

  def _count(key: str) -> int | None:
    val = ontology_data.get(key)
    return int(val) if isinstance(val, (int, float, str)) and str(val).isdigit() else None

  num_terms = _count("numberOfTerms")
  num_props = _count("numberOfProperties")
  num_inds = _count("numberOfIndividuals")
  total_entities = max(1, (num_terms or 0) + (num_props or 0) + (num_inds or 0))

  return {
      "ontology_id": ontology_id,
      "preferred_prefix": preferred_prefix,
      "title": title,
      "description": description,
      "version": version,
      "status": status,
      "loaded": loaded,
      "updated": updated,
      "homepage": homepage,
      "tracker": tracker,
      "number_of_terms": num_terms,
      "number_of_properties": num_props,
      "number_of_individuals": num_inds,
      "composition_ratios": {
          "classes_pct": round(((num_terms or 0) / total_entities) * 100.0, 2),
          "properties_pct": round(((num_props or 0) / total_entities) * 100.0, 2),
          "individuals_pct": round(((num_inds or 0) / total_entities) * 100.0, 2),
      },
      "license": license_norm,
      "roots": roots_norm,
      "root_count": len(roots_norm),
  }


def profile_repository_stats(stats_data: dict[str, Any] | None) -> dict[str, Any] | None:
  """Extracts global OLS4 repository metrics and top ontology class distributions."""
  if not stats_data or not isinstance(stats_data, dict):
    return None

  top_ontologies_raw = stats_data.get("topOntologiesByClasses") or []
  top_ontologies: list[dict[str, Any]] = []
  for item in top_ontologies_raw:
    if isinstance(item, dict):
      top_ontologies.append({
          "ontology_id": str(item.get("ontologyId") or ""),
          "title": str(item.get("title") or ""),
          "preferred_prefix": str(item.get("preferredPrefix") or ""),
          "number_of_classes": int(item.get("numberOfClasses") or 0),
          "number_of_properties": int(item.get("numberOfProperties") or 0),
          "number_of_individuals": int(item.get("numberOfIndividuals") or 0),
      })

  def _count(key: str) -> int | None:
    val = stats_data.get(key)
    return int(val) if isinstance(val, (int, float)) else None

  profile: dict[str, Any] = {
      "number_of_ontologies": _count("numberOfOntologies"),
      "number_of_classes": _count("numberOfClasses"),
      "number_of_properties": _count("numberOfProperties"),
      "number_of_individuals": _count("numberOfIndividuals"),
      "last_modified": str(stats_data.get("lastModified") or ""),
  }
  if stats_data.get("version"):
    profile["version"] = str(stats_data["version"])
  if top_ontologies:
    profile["top_ontologies"] = top_ontologies
  return profile


def build_ontology_visualization_payload(
    ontology_data: dict[str, Any] | None = None,
    stats_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """Combines ontology metadata and global repository stats into a unified profile."""
  if not ontology_data and not stats_data:
    raise ValueError(
        "Provide at least one of ontology_data or stats_data to profile."
    )

  onto_profile = profile_ontology(ontology_data)
  repo_stats = profile_repository_stats(stats_data)

  return {
      "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      "ontology_profile": onto_profile,
      "repository_stats": repo_stats,
      "citations": [
          {"id": "ols4_2025", "text": ols_utils.PRIMARY_CITATION},
          {"id": "ols_2015", "text": ols_utils.ORIGINAL_CITATION},
      ],
      "disclaimer": ols_utils.SCIENTIFIC_DISCLAIMER,
  }


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `visualize_ontology.py`."""
  parser = argparse.ArgumentParser(
      description="Aggregate OLS4 ontology metadata and repository statistics for visualization."
  )
  parser.add_argument(
      "--ontology_json",
      help="Path to ontology metadata JSON file produced by get_ontology.py.",
  )
  parser.add_argument(
      "--stats_json",
      help="Path to global statistics JSON file produced by get_stats.py.",
  )
  parser.add_argument(
      "-o",
      "--output",
      required=True,
      help="Output JSON file path for the ontology profile.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `visualize_ontology.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    onto_data = None
    stats_data = None
    if args.ontology_json:
      p = Path(args.ontology_json)
      if not p.is_file():
        raise FileNotFoundError(f"Ontology JSON file not found: {p}")
      with p.open("r", encoding="utf-8") as handle:
        onto_data = json.load(handle)

    if args.stats_json:
      p = Path(args.stats_json)
      if not p.is_file():
        raise FileNotFoundError(f"Stats JSON file not found: {p}")
      with p.open("r", encoding="utf-8") as handle:
        stats_data = json.load(handle)

    payload = build_ontology_visualization_payload(
        ontology_data=onto_data, stats_data=stats_data
    )
    out_path = ols_utils.write_json_output(payload, args.output)
    print(f"Ontology visualization profile saved to {out_path}.")
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("visualize_ontology failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
