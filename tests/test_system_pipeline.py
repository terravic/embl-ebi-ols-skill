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
"""End-to-end system, pipeline, and licensing verification tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPTS_DIR))

import generate_dashboard  # pylint: disable=wrong-import-position
import run_pipeline  # pylint: disable=wrong-import-position

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_ols_api import patch_ols_api  # pylint: disable=wrong-import-position,import-error


def _embedded_payload(html_text: str) -> dict:
  start = html_text.index("window.__OLS_DATA__ = ") + len("window.__OLS_DATA__ = ")
  end = html_text.index(";\n  </script>", start)
  return json.loads(html_text[start:end].replace("<\\/", "</"))

APACHE_HEADER_PREFIX = (
    '# Licensed under the Apache License, Version 2.0 (the "License");'
)


class TestSystemPipeline(unittest.TestCase):
  """Tests end-to-end pipeline workflows, HTML dashboard outputs, and license guards."""

  def setUp(self) -> None:
    self.patcher, self.api = patch_ols_api()
    self.patcher.start()
    self.addCleanup(self.patcher.stop)

  def test_pipeline_obo_id_nucleus(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(
          ["--obo_id", "GO:0005634", "-o", tmpdir]
      )
      self.assertEqual(rc, 0)
      out = Path(tmpdir)
      self.assertTrue((out / "term.json").is_file())
      self.assertTrue((out / "hierarchy_graph.json").is_file())
      self.assertTrue((out / "dashboard.html").is_file())

      html_content = (out / "dashboard.html").read_text(encoding="utf-8")
      self.assertIn(
          "https://cdn.tailwindcss.com",
          html_content,
      )
      self.assertIn(
          "https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js",
          html_content,
      )
      self.assertIn("--bg-main", html_content)
      self.assertIn("--bg-card", html_content)
      self.assertIn("--border-color", html_content)
      self.assertIn("--text-main", html_content)
      self.assertIn("--text-muted", html_content)
      self.assertIn("--accent", html_content)
      # Verify DESIGN.md Section 1 & 3 Typography and Theme Tokens
      self.assertIn("DM Sans", html_content)
      self.assertIn("Instrument Serif", html_content)
      self.assertIn("IBM Plex Mono", html_content)
      self.assertIn("#FAFAF9", html_content)
      self.assertIn("#FFFFFF", html_content)
      self.assertIn("#E7E5E4", html_content)
      self.assertIn("#1C1917", html_content)
      self.assertIn("#787774", html_content)
      self.assertIn("#0D0E11", html_content)
      self.assertIn("#16171D", html_content)
      self.assertIn("#292A30", html_content)
      self.assertIn("#ECE8E2", html_content)
      self.assertIn("#9A9895", html_content)
      # Verify DESIGN.md Section 3 Three-Icon Theme Selector
      self.assertIn("theme-btn-light", html_content)
      self.assertIn("theme-btn-dark", html_content)
      self.assertIn("theme-btn-system", html_content)
      self.assertIn('data-theme-mode="light"', html_content)
      self.assertIn('data-theme-mode="dark"', html_content)
      self.assertIn('data-theme-mode="system"', html_content)
      self.assertIn("system_theme", html_content)
      # Verify DESIGN.md Section 4 & 5 Semantic Visualization Palette & Titles
      self.assertIn("#0D9488", html_content)
      self.assertIn("#D97706", html_content)
      self.assertIn("#4F46E5", html_content)
      self.assertIn("#059669", html_content)
      self.assertIn("#E11D48", html_content)
      self.assertIn("Structural Data Diagram", html_content)
      self.assertIn("Interactive Relationship Node Map", html_content)
      self.assertIn("EventSource", html_content)
      self.assertIn("network-3d-mount", html_content)
      self.assertIn("3D Network", html_content)
      self.assertIn("2D Hierarchy", html_content)
      self.assertIn("Lineage Tree", html_content)
      self.assertIn("Data Pipeline", html_content)
      self.assertIn("Corpus Metrics", html_content)
      self.assertIn("btn-theme-light", html_content)
      self.assertIn("btn-theme-dark", html_content)
      self.assertIn("McLaughlin, J.", html_content)
      self.assertIn("Jupp, S.", html_content)
      self.assertIn("clinical diagnostic or medical treatment decisions", html_content)

  def test_pipeline_disease_doid_9351(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(
          [
              "--obo_id",
              "DOID:9351",
              "--relations",
              "parents,children,ancestors",
              "-o",
              tmpdir,
          ]
      )
      self.assertEqual(rc, 0)
      graph_data = json.loads(
          (Path(tmpdir) / "hierarchy_graph.json").read_text(encoding="utf-8")
      )
      self.assertEqual(graph_data["target_term"]["id"], "DOID:9351")
      self.assertEqual(graph_data["target_term"]["label"], "diabetes mellitus")

  def test_pipeline_keyword_query_apoptosis(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(
          ["--query", "apoptosis", "--ontology", "go", "-o", tmpdir]
      )
      self.assertEqual(rc, 0)
      out = Path(tmpdir)
      self.assertTrue((out / "search_results.json").is_file())
      graph_data = json.loads(
          (out / "hierarchy_graph.json").read_text(encoding="utf-8")
      )
      self.assertEqual(graph_data["target_term"]["id"], "GO:0006915")

  def test_pipeline_ontology_overview_and_stats(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(
          ["--ontology", "go", "--stats", "-o", tmpdir]
      )
      self.assertEqual(rc, 0)
      out = Path(tmpdir)
      self.assertTrue((out / "ontology.json").is_file())
      self.assertTrue((out / "stats.json").is_file())
      self.assertTrue((out / "ontology_profile.json").is_file())
      self.assertTrue((out / "dashboard.html").is_file())

  def test_subprocess_cli_execution(self) -> None:
    for script_base in (
        SCRIPTS_DIR,
        PROJECT_ROOT / "skills" / "embl_ebi_ols_visualize" / "scripts",
    ):
      if not script_base.is_dir():
        continue
      script = str(script_base / "run_pipeline.py")
      proc = subprocess.run(
          [sys.executable, script, "--help"], capture_output=True, text=True, check=False
      )
      self.assertEqual(proc.returncode, 0, msg=proc.stderr)
      self.assertNotIn("--mock", proc.stdout)
      proc = subprocess.run(
          [sys.executable, script, "--obo_id", "GO:0005634", "--mock", "-o", "unused"],
          capture_output=True, text=True, check=False,
      )
      self.assertNotEqual(proc.returncode, 0)

  def test_examples_are_isolated_from_live_data(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(["--obo_id", "DOID:9351", "-o", tmpdir])
      self.assertEqual(rc, 0)
      payload = _embedded_payload(
          (Path(tmpdir) / "dashboard.html").read_text(encoding="utf-8")
      )
    self.assertEqual(payload["source"], "live")
    self.assertNotIn("presets", payload)
    # No ontology/stats were fetched, so nothing is back-filled from examples.
    self.assertIsNone(payload["ontology_profile"])
    self.assertIsNone(payload["repository_stats"])
    self.assertEqual(payload["target_term"]["id"], "DOID:9351")
    self.assertEqual(sorted(payload["examples"]), ["GO:0005634", "GO:0006915"])
    for ex in payload["examples"].values():
      self.assertEqual(ex["source"], "example")
      self.assertIsNone(ex["repository_stats"])
      self.assertEqual(ex["ontology_profile"]["ontology_id"], "go")

  def test_dashboard_without_inputs_is_not_backfilled(self) -> None:
    term = json.loads(
        (PROJECT_ROOT / "sample_data" / "doid_9351_diabetes.json").read_text(encoding="utf-8")
    )
    data = generate_dashboard.assemble_dashboard_data(term_data=term)
    self.assertIsNone(data["ontology_profile"])
    self.assertIsNone(data["repository_stats"])
    self.assertNotIn("DOID:9351", data["examples"])

  def test_ontology_only_run_has_no_invented_term(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(["--ontology", "go", "-o", tmpdir])
      self.assertEqual(rc, 0)
      payload = _embedded_payload(
          (Path(tmpdir) / "dashboard.html").read_text(encoding="utf-8")
      )
    self.assertIsNone(payload["target_term"])
    self.assertEqual(payload["nodes"], [])
    self.assertEqual(payload["ontology_profile"]["ontology_id"], "go")

  @unittest.skipUnless(
      os.environ.get("OLS4_LIVE_TESTS") == "1", "set OLS4_LIVE_TESTS=1 to query the live API"
  )
  def test_live_pipeline_against_ols4(self) -> None:
    self.patcher.stop()
    self.addCleanup(self.patcher.start)
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(["--obo_id", "GO:0005634", "--stats", "-o", tmpdir])
      self.assertEqual(rc, 0)
      payload = _embedded_payload(
          (Path(tmpdir) / "dashboard.html").read_text(encoding="utf-8")
      )
    self.assertEqual(payload["target_term"]["id"], "GO:0005634")
    self.assertGreater(payload["repository_stats"]["number_of_ontologies"], 264)
    self.assertEqual(payload["processing_summary"]["unconnected_nodes"], 0)
    self.assertTrue(any(p[0].startswith("BFO:") for p in payload["root_paths"]))

  def test_apache_headers_and_licenses(self) -> None:
    script_dirs = [SCRIPTS_DIR]
    nested_scripts = PROJECT_ROOT / "skills" / "embl_ebi_ols_visualize" / "scripts"
    if nested_scripts.is_dir():
      script_dirs.append(nested_scripts)

    for sdir in script_dirs:
      for py_file in sdir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        self.assertTrue(
            content.startswith(APACHE_HEADER_PREFIX),
            msg=f"Missing Apache 2.0 header in {py_file}",
        )

    skill_licenses = (PROJECT_ROOT / "SKILL_LICENSES.md").read_text(encoding="utf-8")
    self.assertIn(
        "embl-ebi-ols-visualize | https://www.ebi.ac.uk/ols4/api-docs and https://www.ebi.ac.uk/about/terms-of-use/",
        skill_licenses,
    )


if __name__ == "__main__":
  unittest.main()
