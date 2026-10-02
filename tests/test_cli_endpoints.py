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
"""CLI smoke and endpoint wrapper tests for all modular scripts in `scripts/`."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPTS_DIR))

import generate_dashboard  # pylint: disable=wrong-import-position
import get_individual  # pylint: disable=wrong-import-position
import get_ontology  # pylint: disable=wrong-import-position
import get_property  # pylint: disable=wrong-import-position
import get_stats  # pylint: disable=wrong-import-position
import get_term  # pylint: disable=wrong-import-position
import search_ols  # pylint: disable=wrong-import-position
import suggest_ols  # pylint: disable=wrong-import-position
import visualize_hierarchy  # pylint: disable=wrong-import-position
import visualize_ontology  # pylint: disable=wrong-import-position


class TestCliEndpoints(unittest.TestCase):
  """Tests all modular CLI scripts in `--mock` mode."""

  def test_search_and_suggest_cli(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      search_out = Path(tmpdir) / "search.json"
      rc = search_ols.main(
          ["--query", "diabetes", "--rows", "5", "--mock", "--output", str(search_out)]
      )
      self.assertEqual(rc, 0)
      data = json.loads(search_out.read_text(encoding="utf-8"))
      docs = data["response"]["docs"]
      self.assertGreaterEqual(len(docs), 1)
      self.assertEqual(docs[0]["obo_id"], "DOID:9351")

      suggest_out = Path(tmpdir) / "suggest.json"
      rc_sug = suggest_ols.main(
          ["--query", "diabet", "--rows", "5", "--mock", "--output", str(suggest_out)]
      )
      self.assertEqual(rc_sug, 0)
      sug_data = json.loads(suggest_out.read_text(encoding="utf-8"))
      self.assertGreaterEqual(len(sug_data["response"]["docs"]), 1)

  def test_get_term_property_individual_ontology_stats_cli(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      tmp = Path(tmpdir)

      # 1. get_term.py
      term_out = tmp / "term.json"
      rc = get_term.main(
          [
              "--obo_id",
              "GO:0005634",
              "--relations",
              "parents,children,ancestors,hierarchicalParents,hierarchicalChildren",
              "--summary",
              "--mock",
              "--output",
              str(term_out),
          ]
      )
      self.assertEqual(rc, 0)
      term_json = json.loads(term_out.read_text(encoding="utf-8"))
      self.assertEqual(term_json["obo_id"], "GO:0005634")
      self.assertIn("relations", term_json)
      self.assertIn("parents", term_json["relations"])

      # 2. get_property.py
      prop_out = tmp / "property.json"
      rc = get_property.main(
          [
              "--obo_id",
              "BFO:0000050",
              "--ontology",
              "ro",
              "--relations",
              "parents,children",
              "--mock",
              "--output",
              str(prop_out),
          ]
      )
      self.assertEqual(rc, 0)
      prop_json = json.loads(prop_out.read_text(encoding="utf-8"))
      self.assertEqual(prop_json["label"], "part_of")

      # 3. get_individual.py
      ind_out = tmp / "individual.json"
      rc = get_individual.main(
          [
              "--obo_id",
              "RO:0001901",
              "--ontology",
              "ro",
              "--relations",
              "types",
              "--mock",
              "--output",
              str(ind_out),
          ]
      )
      self.assertEqual(rc, 0)
      ind_json = json.loads(ind_out.read_text(encoding="utf-8"))
      self.assertEqual(ind_json["obo_id"], "RO:0001901")

      # 4. get_ontology.py
      onto_out = tmp / "ontology.json"
      rc = get_ontology.main(
          ["--ontology", "go", "--mock", "--output", str(onto_out)]
      )
      self.assertEqual(rc, 0)
      onto_json = json.loads(onto_out.read_text(encoding="utf-8"))
      self.assertEqual(onto_json["ontologyId"], "go")

      # 5. get_stats.py
      stats_out = tmp / "stats.json"
      rc = get_stats.main(["--mock", "--output", str(stats_out)])
      self.assertEqual(rc, 0)
      stats_json = json.loads(stats_out.read_text(encoding="utf-8"))
      self.assertEqual(stats_json["numberOfOntologies"], 264)

      # 6. visualize_hierarchy.py
      graph_out = tmp / "graph.json"
      rc = visualize_hierarchy.main(
          ["--term_json", str(term_out), "--output", str(graph_out)]
      )
      self.assertEqual(rc, 0)

      # 7. visualize_ontology.py
      onto_prof_out = tmp / "onto_profile.json"
      rc = visualize_ontology.main(
          [
              "--ontology_json",
              str(onto_out),
              "--stats_json",
              str(stats_out),
              "--output",
              str(onto_prof_out),
          ]
      )
      self.assertEqual(rc, 0)

      # 8. generate_dashboard.py
      dash_out = tmp / "dashboard.html"
      rc = generate_dashboard.main(
          [
              "--term_json",
              str(term_out),
              "--graph_json",
              str(graph_out),
              "--ontology_json",
              str(onto_out),
              "--stats_json",
              str(stats_out),
              "--output",
              str(dash_out),
          ]
      )
      self.assertEqual(rc, 0)
      self.assertTrue(dash_out.is_file())
      html_text = dash_out.read_text(encoding="utf-8")
      self.assertIn("cdn.tailwindcss.com", html_text)
      self.assertIn("d3.min.js", html_text)
      self.assertIn("window.__OLS_DATA__", html_text)


if __name__ == "__main__":
  unittest.main()
