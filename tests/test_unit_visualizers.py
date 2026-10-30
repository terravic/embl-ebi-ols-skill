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
"""Unit tests for `visualize_hierarchy.py` and `visualize_ontology.py`."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
if str(SCRIPTS_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPTS_DIR))

import ols_utils  # pylint: disable=wrong-import-position
import visualize_hierarchy  # pylint: disable=wrong-import-position
import visualize_ontology  # pylint: disable=wrong-import-position


class TestVisualizersUnit(unittest.TestCase):
  """Tests DAG extraction, semantic edge classification, root paths, and ontology profiling."""

  def test_nucleus_hierarchy_and_partonomic_edges(self) -> None:
    term_data = ols_utils.load_example_data("go_0005634_nucleus.json")
    payload = visualize_hierarchy.build_hierarchy_payload(term_data)

    self.assertEqual(payload["target_term"]["id"], "GO:0005634")
    self.assertEqual(payload["target_term"]["label"], "nucleus")
    self.assertGreater(len(payload["nodes"]), 10)
    self.assertGreater(len(payload["edges"]), 10)

    edge_types = {e["type"] for e in payload["edges"]}
    self.assertIn("subClassOf", edge_types)
    self.assertIn("part_of", edge_types)

    for edge in payload["edges"]:
      if edge["type"] == "subClassOf":
        self.assertFalse(edge["is_hierarchical"])
        self.assertEqual(edge["style"]["pattern"], "solid")
      elif edge["type"] == "part_of":
        self.assertTrue(edge["is_hierarchical"])
        self.assertEqual(edge["style"]["pattern"], "dashed")

    # Verify shortest root path from cellular_component (GO:0005575) to nucleus (GO:0005634)
    self.assertTrue(len(payload["root_paths"]) >= 1)
    first_path = payload["root_paths"][0]
    self.assertEqual(first_path[0], "GO:0005575")
    self.assertEqual(first_path[-1], "GO:0005634")

  def test_diabetes_multi_parent_diamond_inheritance(self) -> None:
    term_data = ols_utils.load_example_data("doid_9351_diabetes.json")
    payload = visualize_hierarchy.build_hierarchy_payload(term_data)

    parent_ids = {p["id"] for p in payload["target_term"]["parents"]}
    self.assertIn("DOID:4194", parent_ids)
    self.assertIn("DOID:28", parent_ids)

    xref_dbs = {x["database"] for x in payload["target_term"]["xrefs"]}
    self.assertIn("ICD10CM", xref_dbs)
    self.assertIn("MeSH", xref_dbs)
    self.assertIn("OMIM", xref_dbs)

    # Ensure the collapsible tree starts at the real top term DOID:4 (disease)
    self.assertEqual([t["id"] for t in payload["trees"]], ["DOID:4"])
    self.assertTrue(len(payload["trees"][0]["children"]) >= 1)

  def test_cyclic_graph_safety(self) -> None:
    cyclic_term = {
        "obo_id": "TEST:0001",
        "label": "cyclic focal term",
        "ontology_name": "test",
        "ontology_prefix": "TEST",
        "description": ["Synthetic term with a cycle for defensive testing."],
        "relations": {
            "parents": [{"obo_id": "TEST:0002", "label": "parent term"}],
            "children": [{"obo_id": "TEST:0003", "label": "child term"}],
            "graph": {
                "nodes": [
                    {"obo_id": "TEST:0001", "label": "cyclic focal term"},
                    {"obo_id": "TEST:0002", "label": "parent term"},
                    {"obo_id": "TEST:0003", "label": "child term"},
                ],
                "edges": [
                    # OLS4 `/graph` edges are subject -> object.
                    {"source": "TEST:0001", "target": "TEST:0002", "label": "subClassOf"},
                    {"source": "TEST:0003", "target": "TEST:0001", "label": "part_of"},
                    {"source": "TEST:0002", "target": "TEST:0003", "label": "develops_from"},
                ],
            },
        },
    }
    payload = visualize_hierarchy.build_hierarchy_payload(cyclic_term)
    self.assertEqual(payload["metrics"]["node_count"], 3)
    self.assertIsInstance(payload["trees"], list)
    self.assertGreaterEqual(len(payload["trees"]), 1)

  def test_ontology_and_stats_profiler(self) -> None:
    onto_raw = ols_utils.load_example_data("ontology_go.json")
    stats_raw = json.loads((FIXTURE_DIR / "stats.json").read_text(encoding="utf-8"))
    profile = visualize_ontology.build_ontology_visualization_payload(
        ontology_data=onto_raw,
        stats_data=stats_raw,
    )
    self.assertEqual(profile["ontology_profile"]["ontology_id"], "go")
    self.assertEqual(profile["ontology_profile"]["number_of_terms"], 47852)
    self.assertEqual(profile["ontology_profile"]["root_count"], 3)
    self.assertEqual(profile["repository_stats"]["number_of_ontologies"], 264)
    # Fields absent from the API response are not invented.
    self.assertNotIn("top_ontologies", profile["repository_stats"])
    self.assertNotIn("version", profile["repository_stats"])

  def test_missing_values_are_not_invented(self) -> None:
    profile = visualize_ontology.profile_ontology({"ontologyId": "xyz", "config": {}})
    self.assertEqual(profile["title"], "")
    self.assertEqual(profile["version"], "")
    self.assertEqual(profile["license"]["label"], "")
    self.assertIsNone(profile["number_of_terms"])
    self.assertIsNone(visualize_hierarchy.canonical_node_id({"label": "no id"}))

    term = {
        "obo_id": "TEST:1",
        "label": "t",
        "synonyms": ["plain synonym"],
        "obo_xref": [{"id": "123"}],
        "relations": {
            "ancestors": [{"obo_id": "TEST:9", "label": "far ancestor"}],
            "hierarchicalParents": [{"obo_id": "TEST:2", "label": "hp"}],
            "parents": [{"obo_id": "TEST:3", "label": "p"}],
        },
    }
    payload = visualize_hierarchy.build_hierarchy_payload(term)
    ids = {n["id"] for n in payload["nodes"]}
    # An ancestor with no connecting edge is not wired into an invented lineage.
    self.assertNotIn("TEST:9", ids)
    self.assertEqual(payload["processing_summary"]["unconnected_nodes"], 1)
    self.assertFalse(any("UNKNOWN" in i for i in ids))
    types = {(e["source"], e["type"]) for e in payload["edges"]}
    self.assertIn(("TEST:3", "subClassOf"), types)
    # Untyped hierarchical parent is not guessed to be part_of.
    self.assertIn(("TEST:2", "hierarchical"), types)
    self.assertEqual(payload["target_term"]["synonyms"][0]["scope"], "")
    self.assertEqual(payload["target_term"]["xrefs"][0]["database"], "")
    # No fabricated virtual root: each real top-level term is its own tree.
    self.assertEqual(sorted(t["id"] for t in payload["trees"]), ["TEST:2", "TEST:3"])
    self.assertFalse(payload["nodes"][0]["is_root"])

  def test_lineage_records_connect_ancestors(self) -> None:
    term = {
        "obo_id": "TEST:1",
        "label": "t",
        "relations": {
            "parents": [{"obo_id": "TEST:2", "iri": "http://x/TEST_2", "label": "p"}],
            "ancestors": [
                {"obo_id": "TEST:2", "iri": "http://x/TEST_2", "label": "p"},
                {"obo_id": "TEST:3", "iri": "http://x/TEST_3", "label": "gp", "is_root": True},
            ],
            "lineage": [
                {"iri": "http://x/TEST_2", "obo_id": "TEST:2",
                 "parents": [{"obo_id": "TEST:3", "iri": "http://x/TEST_3"}],
                 "hierarchicalParents": []},
                {"iri": "http://x/TEST_3", "obo_id": "TEST:3",
                 "parents": [], "hierarchicalParents": []},
            ],
        },
    }
    payload = visualize_hierarchy.build_hierarchy_payload(term)
    self.assertEqual(payload["root_paths"], [["TEST:3", "TEST:2", "TEST:1"]])
    depths = {n["id"]: n["depth"] for n in payload["nodes"]}
    self.assertEqual(depths, {"TEST:3": -2, "TEST:2": -1, "TEST:1": 0})

if __name__ == "__main__":
  unittest.main()
