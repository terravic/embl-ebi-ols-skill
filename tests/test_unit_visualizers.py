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

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPTS_DIR))

import ols_utils  # pylint: disable=wrong-import-position
import visualize_hierarchy  # pylint: disable=wrong-import-position
import visualize_ontology  # pylint: disable=wrong-import-position


class TestVisualizersUnit(unittest.TestCase):
  """Tests DAG extraction, semantic edge classification, root paths, and ontology profiling."""

  def test_nucleus_hierarchy_and_partonomic_edges(self) -> None:
    term_data = ols_utils.load_mock_data("go_0005634_nucleus.json")
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
    term_data = ols_utils.load_mock_data("doid_9351_diabetes.json")
    payload = visualize_hierarchy.build_hierarchy_payload(term_data)

    parent_ids = {p["id"] for p in payload["target_term"]["parents"]}
    self.assertIn("DOID:4194", parent_ids)
    self.assertIn("DOID:28", parent_ids)

    xref_dbs = {x["database"] for x in payload["target_term"]["xrefs"]}
    self.assertIn("ICD10CM", xref_dbs)
    self.assertIn("MeSH", xref_dbs)
    self.assertIn("OMIM", xref_dbs)

    # Ensure collapsible tree root is DOID:4 (disease)
    self.assertEqual(payload["tree"]["id"], "DOID:4")
    self.assertTrue(len(payload["tree"]["children"]) >= 2)

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
                    {"source": "TEST:0002", "target": "TEST:0001", "label": "subClassOf"},
                    {"source": "TEST:0001", "target": "TEST:0003", "label": "part_of"},
                    {"source": "TEST:0003", "target": "TEST:0002", "label": "develops_from"},
                ],
            },
        },
    }
    payload = visualize_hierarchy.build_hierarchy_payload(cyclic_term)
    self.assertEqual(payload["metrics"]["node_count"], 3)
    self.assertIsInstance(payload["tree"], dict)

  def test_ontology_and_stats_profiler(self) -> None:
    onto_raw = ols_utils.load_mock_data("ontology_go.json")
    stats_raw = ols_utils.load_mock_data("stats.json")
    profile = visualize_ontology.build_ontology_visualization_payload(
        ontology_data=onto_raw,
        stats_data=stats_raw,
    )
    self.assertEqual(profile["ontology_profile"]["ontology_id"], "go")
    self.assertEqual(profile["ontology_profile"]["number_of_terms"], 47852)
    self.assertEqual(profile["ontology_profile"]["root_count"], 3)
    self.assertEqual(profile["repository_stats"]["number_of_ontologies"], 264)
    self.assertGreater(len(profile["repository_stats"]["top_ontologies"]), 5)


if __name__ == "__main__":
  unittest.main()
