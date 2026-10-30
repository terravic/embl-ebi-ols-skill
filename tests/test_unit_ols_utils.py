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
"""Unit tests for `scripts/ols_utils.py`."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPTS_DIR))

import ols_utils  # pylint: disable=wrong-import-position


class TestOlsUtilsUnit(unittest.TestCase):
  """Tests IRI conversion, double encoding, prefix resolution, license guard, and transport."""

  def test_obo_id_to_iri_and_normalization(self) -> None:
    self.assertEqual(
        ols_utils.obo_id_to_iri("GO:0005634"),
        "http://purl.obolibrary.org/obo/GO_0005634",
    )
    self.assertEqual(
        ols_utils.obo_id_to_iri("doid:9351"),
        "http://purl.obolibrary.org/obo/DOID_9351",
    )
    self.assertEqual(
        ols_utils.obo_id_to_iri("GO_0006915"),
        "http://purl.obolibrary.org/obo/GO_0006915",
    )
    self.assertEqual(
        ols_utils.iri_to_obo_id("http://purl.obolibrary.org/obo/GO_0005634"),
        "GO:0005634",
    )

  def test_invalid_obo_id_raises(self) -> None:
    with self.assertRaises(ValueError):
      ols_utils.obo_id_to_iri("")
    with self.assertRaises(ValueError):
      ols_utils.obo_id_to_iri("GO0005634")
    with self.assertRaises(ValueError):
      ols_utils.obo_id_to_iri("INVALID_WITHOUT_PROPER_OBO_ID")
    with self.assertRaises(ValueError):
      ols_utils.normalize_obo_id("GO:")

  def test_double_encode_iri(self) -> None:
    iri = "http://purl.obolibrary.org/obo/GO_0005634"
    encoded = ols_utils.double_encode_iri(iri)
    self.assertEqual(
        encoded,
        "http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FGO_0005634",
    )
    with self.assertRaises(ValueError):
      ols_utils.double_encode_iri("   ")

  def test_resolve_ontology_mappings(self) -> None:
    for prefix, expected_slug in ols_utils.OBO_PREFIX_TO_ONTOLOGY.items():
      self.assertEqual(
          ols_utils.resolve_ontology(f"{prefix}:0000001", None),
          expected_slug,
      )
    self.assertEqual(
        ols_utils.resolve_ontology("GO:0005634", "custom_onto"),
        "custom_onto",
    )
    with self.assertRaises(ValueError):
      ols_utils.resolve_ontology(None, None)

  def test_verify_license_guard_creates_timestamped_file(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      guard_path = ols_utils.verify_license_guard(workspace_root=tmpdir)
      self.assertTrue(guard_path.is_file())
      self.assertEqual(guard_path.name, "embl_ebi_ols_visualize_LICENSE.txt")
      content = guard_path.read_text(encoding="utf-8")
      self.assertIn("https://www.ebi.ac.uk/ols4/api-docs", content)
      self.assertIn("https://www.ebi.ac.uk/about/terms-of-use/", content)
      self.assertRegex(
          content, r"Timestamp:\s+\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
      )

  def test_rate_limit_enforcement(self) -> None:
    ols_utils._LAST_REQUEST_MONOTONIC = 0.0
    ols_utils._enforce_rate_limit()
    t0 = time.monotonic()
    ols_utils._enforce_rate_limit()
    elapsed = time.monotonic() - t0
    self.assertGreaterEqual(elapsed, ols_utils.RATE_LIMIT_DELAY * 0.85)

  def test_load_example_data(self) -> None:
    nucleus = ols_utils.load_example_data("go_0005634_nucleus.json")
    self.assertEqual(nucleus["obo_id"], "GO:0005634")
    self.assertEqual(nucleus["label"], "nucleus")

    diabetes = ols_utils.load_example_data("doid_9351_diabetes.json")
    self.assertEqual(diabetes["obo_id"], "DOID:9351")

    with self.assertRaises(FileNotFoundError):
      ols_utils.load_example_data("non_existent_file_xyz.json")

  def test_no_offline_mock_engine_in_production_code(self) -> None:
    self.assertFalse(hasattr(ols_utils, "_dispatch_mock_request"))
    self.assertFalse(hasattr(ols_utils, "load_mock_data"))
    self.assertNotIn("mock", ols_utils.make_request.__code__.co_varnames)

  def test_make_request_uses_live_transport(self) -> None:
    calls = []

    def fake_get(url, headers):
      calls.append(url)
      return {"numberOfOntologies": 1}

    with mock.patch.object(ols_utils, "_http_get", side_effect=fake_get), \
         mock.patch.object(ols_utils, "RATE_LIMIT_DELAY", 0.0):
      result = ols_utils.make_request("v2/stats", params={"a": True})
    self.assertEqual(result, {"numberOfOntologies": 1})
    self.assertEqual(calls, [f"{ols_utils.BASE_URL}/v2/stats?a=true"])

if __name__ == "__main__":
  unittest.main()
