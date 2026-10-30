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
"""Test-only stand-in for the OLS4 HTTP API.

Production code has no offline mode. Tests patch `ols_utils._http_get` with
`FakeOlsApi` so the full pipeline runs against recorded responses in
`sample_data/` and `tests/fixtures/`. Unknown resources return HTTP 404, just
like the real API, instead of substituting other data.
"""

from __future__ import annotations

import copy
import email.message
import io
import json
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = PROJECT_ROOT / "sample_data"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

TERM_FILES = (
    "go_0005634_nucleus.json",
    "doid_9351_diabetes.json",
    "go_0006915_apoptosis.json",
)

TERM_LIST_RELATIONS = (
    "parents",
    "children",
    "ancestors",
    "descendants",
    "hierarchicalParents",
    "hierarchicalChildren",
    "hierarchicalAncestors",
    "hierarchicalDescendants",
)


def _load(path: Path) -> dict[str, Any]:
  return json.loads(path.read_text(encoding="utf-8"))


def _not_found(url: str) -> urllib.error.HTTPError:
  return urllib.error.HTTPError(
      url, 404, "Not Found", email.message.Message(), io.BytesIO(b"")
  )


def _embedded(key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
  return {
      "_embedded": {key: copy.deepcopy(items)},
      "page": {
          "size": len(items),
          "totalElements": len(items),
          "totalPages": 1,
          "number": 0,
      },
  }


class FakeOlsApi:
  """Routes OLS4 request URLs to recorded JSON responses."""

  def __init__(self) -> None:
    self.terms: dict[str, dict[str, Any]] = {}
    self.term_records: dict[str, dict[str, Any]] = {}
    for fname in TERM_FILES:
      term = _load(SAMPLE_DIR / fname)
      self.terms[term["iri"]] = term
      self.term_records[term["iri"]] = term
      for key in TERM_LIST_RELATIONS:
        for item in term.get("relations", {}).get(key, []) or []:
          if isinstance(item, dict) and item.get("iri"):
            self.term_records.setdefault(item["iri"], item)
    self.ontology_go = _load(SAMPLE_DIR / "ontology_go.json")
    self.stats = _load(FIXTURE_DIR / "stats.json")
    self.search = _load(FIXTURE_DIR / "search_diabetes.json")
    # Real responses recorded from the live API (keyed by decoded URL path).
    self.recorded = _load(FIXTURE_DIR / "recorded_responses.json")
    self.requested_urls: list[str] = []

  # -- helpers ---------------------------------------------------------------
  def _graph_parents(self, iri: str) -> list[dict[str, Any]]:
    """Parents of any term found in a recorded `/graph` (child -> parent edges)."""
    parents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term in self.terms.values():
      graph = term.get("relations", {}).get("graph") or {}
      for edge in graph.get("edges") or []:
        if edge.get("source") == iri and edge.get("target") not in seen:
          seen.add(edge["target"])
          rec = dict(self.term_records.get(edge["target"], {"iri": edge["target"]}))
          rec["relation_type"] = edge.get("label")
          parents.append(rec)
    return parents

  def _search(self, params: dict[str, str]) -> dict[str, Any]:
    docs = self.search.get("response", {}).get("docs", [])
    query = params.get("q", "").strip().lower()
    onto = params.get("ontology", "").strip().lower()
    exact = params.get("exact", "") == "true"
    hits = []
    for doc in docs:
      if onto and doc.get("ontology_name", "").lower() != onto:
        continue
      label = str(doc.get("label", "")).lower()
      syns = [str(s).lower() for s in doc.get("synonyms", [])]
      if exact:
        match = query in (label, str(doc.get("obo_id", "")).lower()) or query in syns
      else:
        match = query in label or any(query in s for s in syns)
      if match:
        hits.append(doc)
    start = int(params.get("start", 0))
    rows = int(params.get("rows", 10))
    return {
        "responseHeader": {"status": 0},
        "response": {"numFound": len(hits), "start": start, "docs": hits[start : start + rows]},
    }

  # -- router ----------------------------------------------------------------
  def __call__(self, request_url: str, headers: dict[str, str]) -> dict[str, Any]:
    del headers
    self.requested_urls.append(request_url)
    parsed = urllib.parse.urlparse(request_url)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    path = urllib.parse.unquote(urllib.parse.unquote(parsed.path)).rstrip("/")

    for key, body in self.recorded.items():
      if path.endswith(key):
        return copy.deepcopy(body)
    if path.endswith("/v2/stats"):
      return copy.deepcopy(self.stats)
    if path.endswith("/search") or path.endswith("/suggest"):
      return self._search(params)
    if path.endswith("/ontologies/go"):
      return copy.deepcopy(self.ontology_go)
    if path.endswith("/ontologies/go/terms/roots"):
      return _embedded("terms", self.ontology_go.get("roots", []))

    if "/terms/" in path:
      tail = path.split("/terms/", 1)[1]
      for rel in TERM_LIST_RELATIONS + ("graph",):
        if tail.endswith("/" + rel):
          iri = tail[: -(len(rel) + 1)]
          term = self.terms.get(iri)
          if term is not None:
            data = term.get("relations", {}).get(rel)
            if rel == "graph":
              return copy.deepcopy(data or {"nodes": [], "edges": []})
            return _embedded("terms", data or [])
          if iri in self.term_records and rel in ("parents", "hierarchicalParents"):
            return _embedded("terms", self._graph_parents(iri))
          raise _not_found(request_url)
      term = self.terms.get(tail)
      if term is not None:
        body = copy.deepcopy(term)
        body.pop("relations", None)
        return body
    raise _not_found(request_url)


def patch_ols_api() -> tuple[Any, FakeOlsApi]:
  """Returns `(patcher, api)`; start the patcher in setUp and stop it in tearDown."""
  import ols_utils  # pylint: disable=import-outside-toplevel

  api = FakeOlsApi()
  patcher = mock.patch.multiple(
      ols_utils, _http_get=mock.Mock(side_effect=api), RATE_LIMIT_DELAY=0.0
  )
  return patcher, api
