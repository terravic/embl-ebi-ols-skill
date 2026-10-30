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
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPTS_DIR))

import run_pipeline  # pylint: disable=wrong-import-position

APACHE_HEADER_PREFIX = (
    '# Licensed under the Apache License, Version 2.0 (the "License");'
)


class TestSystemPipeline(unittest.TestCase):
  """Tests end-to-end pipeline workflows, HTML dashboard outputs, and license guards."""

  def test_pipeline_obo_id_nucleus_mock(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(
          ["--obo_id", "GO:0005634", "--mock", "-o", tmpdir]
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

  def test_pipeline_disease_doid_9351_mock(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(
          [
              "--obo_id",
              "DOID:9351",
              "--relations",
              "parents,children,ancestors",
              "--mock",
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

  def test_pipeline_keyword_query_apoptosis_mock(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(
          ["--query", "apoptosis", "--ontology", "go", "--mock", "-o", tmpdir]
      )
      self.assertEqual(rc, 0)
      out = Path(tmpdir)
      self.assertTrue((out / "search_results.json").is_file())
      graph_data = json.loads(
          (out / "hierarchy_graph.json").read_text(encoding="utf-8")
      )
      self.assertEqual(graph_data["target_term"]["id"], "GO:0006915")

  def test_pipeline_ontology_overview_and_stats_mock(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      rc = run_pipeline.main(
          ["--ontology", "go", "--stats", "--mock", "-o", tmpdir]
      )
      self.assertEqual(rc, 0)
      out = Path(tmpdir)
      self.assertTrue((out / "ontology.json").is_file())
      self.assertTrue((out / "stats.json").is_file())
      self.assertTrue((out / "ontology_profile.json").is_file())
      self.assertTrue((out / "dashboard.html").is_file())

  def test_subprocess_cli_execution(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      for script_base in (
          SCRIPTS_DIR,
          PROJECT_ROOT / "skills" / "embl_ebi_ols_visualize" / "scripts",
      ):
        if not script_base.is_dir():
          continue
        sub_out = Path(tmpdir) / script_base.parent.name
        cmd = [
            sys.executable,
            str(script_base / "run_pipeline.py"),
            "--obo_id",
            "GO:0005634",
            "--mock",
            "-o",
            str(sub_out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("GO:0005634", proc.stdout)
        self.assertTrue((sub_out / "dashboard.html").is_file())

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
