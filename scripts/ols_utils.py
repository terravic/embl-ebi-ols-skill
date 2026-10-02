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
"""Shared utilities, rate-limited HTTP transport, and mock engine for EMBL-EBI OLS4."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

try:
  import polite_http  # type: ignore
  HAS_POLITE_HTTP = True
except ImportError:
  polite_http = None
  HAS_POLITE_HTTP = False

LOGGER = logging.getLogger("embl_ebi_ols_visualize")
if not LOGGER.handlers:
  _handler = logging.StreamHandler(sys.stderr)
  _handler.setFormatter(
      logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
  )
  LOGGER.addHandler(_handler)
  LOGGER.setLevel(logging.INFO)

BASE_URL = os.environ.get(
    "OLS4_BASE_URL", "https://www.ebi.ac.uk/ols4/api"
).rstrip("/")
RATE_LIMIT_DELAY = float(os.environ.get("OLS4_RATE_LIMIT_DELAY", "0.2"))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("OLS4_TIMEOUT_SECONDS", "30.0"))
MAX_RETRIES = int(os.environ.get("OLS4_MAX_RETRIES", "3"))
USER_AGENT = (
    "embl-ebi-ols-visualize/1.0 "
    "(EMBL-EBI-OLS4-Client; +https://www.ebi.ac.uk/ols4/api-docs)"
)

OBO_PREFIX_TO_ONTOLOGY: dict[str, str] = {
    "GO": "go",
    "DOID": "doid",
    "EFO": "efo",
    "HP": "hp",
    "CHEBI": "chebi",
    "MONDO": "mondo",
    "NCIT": "ncit",
    "CL": "cl",
    "UBERON": "uberon",
    "SO": "so",
    "PR": "pr",
    "PATO": "pato",
    "MP": "mp",
    "OBI": "obi",
    "BFO": "bfo",
    "IAO": "iao",
    "ENVO": "envo",
    "PO": "po",
    "CLO": "clo",
    "DUO": "duo",
    "RO": "ro",
}

VALID_TERM_RELATIONS: tuple[str, ...] = (
    "parents",
    "children",
    "ancestors",
    "descendants",
    "hierarchicalParents",
    "hierarchicalChildren",
    "hierarchicalAncestors",
    "hierarchicalDescendants",
    "graph",
)

LICENSE_NOTICE_TEXT = (
    "Notification: Please check the EMBL-EBI OLS terms of use and licensing at "
    "https://www.ebi.ac.uk/ols4/api-docs and "
    "https://www.ebi.ac.uk/about/terms-of-use/. Data from indexed ontologies "
    "is provided under open-access licenses (e.g., CC BY 4.0, CC0)."
)

PRIMARY_CITATION = (
    "McLaughlin, J., Lagrimas, J., Iqbal, H., Parkinson, H. & Harmse, H. "
    "OLS4: a new Ontology Lookup Service for a growing interdisciplinary "
    "knowledge ecosystem. Bioinformatics 41(5), btaf279 (2025). "
    "doi:10.1093/bioinformatics/btaf279."
)

ORIGINAL_CITATION = (
    "Jupp, S., Burdett, T., Leroy, C. & Parkinson, H. E. "
    "A new Ontology Lookup Service at EMBL-EBI. SWAT4LS, 118-119 (2015)."
)

SCIENTIFIC_DISCLAIMER = (
    "Ontology classifications, hierarchical structures, and cross-references "
    "reflect curated biomedical models and automated inferences from "
    "participating consortiums, and must be independently verified for "
    "clinical diagnostic or medical treatment decisions."
)

_LAST_REQUEST_MONOTONIC: float = 0.0


def get_skill_root() -> Path:
  """Returns the directory containing `scripts/` and `sample_data/`."""
  return Path(__file__).resolve().parent.parent


def get_workspace_root(explicit_root: str | Path | None = None) -> Path:
  """Resolves the top-level repository workspace root directory."""
  if explicit_root is not None:
    return Path(explicit_root).resolve()
  env_root = os.environ.get("OLS_WORKSPACE_ROOT")
  if env_root:
    return Path(env_root).resolve()

  skill_root = get_skill_root()
  # If installed under `<workspace>/skills/embl_ebi_ols_visualize`, step up two levels.
  if (
      skill_root.name == "embl_ebi_ols_visualize"
      and skill_root.parent.name == "skills"
  ):
    return skill_root.parent.parent.resolve()
  return skill_root


def verify_license_guard(workspace_root: str | Path | None = None) -> Path:
  """Verifies or creates `.licenses/embl_ebi_ols_visualize_LICENSE.txt`.

  Args:
    workspace_root: Optional path to the workspace root directory.

  Returns:
    Path to the verified or newly created license guard file.
  """
  root = get_workspace_root(workspace_root)
  license_dir = root / ".licenses"
  primary_guard = license_dir / "embl_ebi_ols_visualize_LICENSE.txt"
  fallback_guard = license_dir / "embl_ebi_ols_LICENSE.txt"

  if primary_guard.is_file() and primary_guard.stat().st_size > 0:
    return primary_guard

  timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
  content = f"{LICENSE_NOTICE_TEXT}\nTimestamp: {timestamp}\n"

  if not fallback_guard.is_file():
    LOGGER.info(LICENSE_NOTICE_TEXT)
    print(LICENSE_NOTICE_TEXT, file=sys.stderr)

  license_dir.mkdir(parents=True, exist_ok=True)
  primary_guard.write_text(content, encoding="utf-8")
  return primary_guard


def normalize_obo_id(obo_id: str) -> str:
  """Normalizes an OBO identifier into canonical `PREFIX:LOCAL_ID` format.

  Args:
    obo_id: Raw OBO ID string (e.g., `GO:0005634` or `GO_0005634`).

  Returns:
    Normalized `PREFIX:LOCAL_ID` string.

  Raises:
    ValueError: If the identifier is empty or lacks a valid prefix separator.
  """
  if not obo_id or not obo_id.strip():
    raise ValueError("OBO identifier must be a non-empty string.")
  cleaned = obo_id.strip()
  if cleaned.startswith(("http://", "https://")):
    short = cleaned.rstrip("/").rsplit("/", 1)[-1]
    if "_" in short:
      prefix, local = short.split("_", 1)
      return f"{prefix.upper()}:{local}"
    raise ValueError(f"Cannot extract OBO identifier from IRI: {obo_id}")

  if ":" in cleaned:
    prefix, local = cleaned.split(":", 1)
  elif cleaned.count("_") == 1:
    prefix, local = cleaned.split("_", 1)
  else:
    raise ValueError(
        f"Invalid OBO ID '{obo_id}'. Expected format 'PREFIX:ID' (e.g., 'GO:0005634')."
    )

  prefix = prefix.strip().upper()
  local = local.strip()
  if not prefix or not local or not prefix.isalnum() or ":" in local:
    raise ValueError(
        f"Invalid OBO ID '{obo_id}'. Both prefix and local ID must be valid and non-empty."
    )
  return f"{prefix}:{local}"


def obo_id_to_iri(obo_id: str) -> str:
  """Converts an OBO ID (`PREFIX:ID`) to `http://purl.obolibrary.org/obo/PREFIX_ID`.

  Args:
    obo_id: Canonical OBO identifier such as `GO:0005634` or `DOID:9351`.

  Returns:
    Canonical OBO Foundry IRI string.
  """
  if obo_id and obo_id.strip().startswith(("http://", "https://")):
    return obo_id.strip()
  normalized = normalize_obo_id(obo_id)
  prefix, local = normalized.split(":", 1)
  return f"http://purl.obolibrary.org/obo/{prefix}_{local}"


def iri_to_obo_id(iri_or_id: str) -> str:
  """Extracts a readable `PREFIX:ID` from an OBO IRI when possible."""
  if not iri_or_id:
    return ""
  text = iri_or_id.strip()
  if text.startswith(("http://", "https://")):
    tail = text.rstrip("/").rsplit("/", 1)[-1]
    if "#" in tail:
      tail = tail.rsplit("#", 1)[-1]
    if "_" in tail:
      prefix, local = tail.split("_", 1)
      if prefix.isalpha():
        return f"{prefix.upper()}:{local}"
    return tail
  try:
    return normalize_obo_id(text)
  except ValueError:
    return text


def double_encode_iri(iri: str) -> str:
  """URL-encodes an IRI twice for safe passage through OLS4 Spring Boot routing.

  Args:
    iri: Full resource IRI (e.g., `http://purl.obolibrary.org/obo/GO_0005634`).

  Returns:
    Double-percent-encoded IRI string.
  """
  if not iri or not iri.strip():
    raise ValueError("IRI must be a non-empty string.")
  single_encoded = urllib.parse.quote(iri.strip(), safe="")
  return urllib.parse.quote(single_encoded, safe="")


def resolve_ontology(obo_id: str | None, ontology: str | None = None) -> str:
  """Resolves the lowercase ontology slug from an explicit flag or OBO prefix.

  Args:
    obo_id: Optional OBO identifier (e.g., `GO:0005634`) or OBO IRI.
    ontology: Optional explicit ontology name (e.g., `go`, `doid`).

  Returns:
    Lowercase ontology identifier string.

  Raises:
    ValueError: If ontology cannot be determined from either argument.
  """
  if ontology and ontology.strip():
    return ontology.strip().lower()

  if obo_id and obo_id.strip():
    normalized = normalize_obo_id(obo_id)
    prefix = normalized.split(":", 1)[0].upper()
    if prefix in OBO_PREFIX_TO_ONTOLOGY:
      return OBO_PREFIX_TO_ONTOLOGY[prefix]
    return prefix.lower()

  raise ValueError(
      "Unable to resolve ontology: provide either --ontology or a valid --obo_id."
  )


def _enforce_rate_limit() -> None:
  """Enforces a minimum delay of `RATE_LIMIT_DELAY` seconds between requests."""
  global _LAST_REQUEST_MONOTONIC
  now = time.monotonic()
  elapsed = now - _LAST_REQUEST_MONOTONIC
  if _LAST_REQUEST_MONOTONIC > 0.0 and elapsed < RATE_LIMIT_DELAY:
    time.sleep(RATE_LIMIT_DELAY - elapsed)
  _LAST_REQUEST_MONOTONIC = time.monotonic()


def load_mock_data(fixture_name: str) -> dict[str, Any]:
  """Loads a JSON fixture from `sample_data/`.

  Args:
    fixture_name: File basename, OBO ID, or logical fixture key.

  Returns:
    Parsed JSON dictionary from `sample_data/`.

  Raises:
    FileNotFoundError: If no matching mock fixture exists.
  """
  sample_dir = get_skill_root() / "sample_data"
  key = fixture_name.strip()

  alias_map: dict[str, str] = {
      "GO:0005634": "go_0005634_nucleus.json",
      "GO_0005634": "go_0005634_nucleus.json",
      "http://purl.obolibrary.org/obo/GO_0005634": "go_0005634_nucleus.json",
      "nucleus": "go_0005634_nucleus.json",
      "DOID:9351": "doid_9351_diabetes.json",
      "DOID_9351": "doid_9351_diabetes.json",
      "http://purl.obolibrary.org/obo/DOID_9351": "doid_9351_diabetes.json",
      "diabetes": "doid_9351_diabetes.json",
      "GO:0006915": "go_0006915_apoptosis.json",
      "GO_0006915": "go_0006915_apoptosis.json",
      "http://purl.obolibrary.org/obo/GO_0006915": "go_0006915_apoptosis.json",
      "apoptosis": "go_0006915_apoptosis.json",
      "apoptotic process": "go_0006915_apoptosis.json",
      "search": "search_diabetes.json",
      "suggest": "search_diabetes.json",
      "ontology": "ontology_go.json",
      "go": "ontology_go.json",
      "stats": "stats.json",
  }

  filename = alias_map.get(key, alias_map.get(key.upper(), key))
  if not filename.endswith(".json"):
    filename = f"{filename}.json"

  candidate = sample_dir / filename
  if not candidate.is_file():
    raise FileNotFoundError(
        f"Mock fixture '{fixture_name}' (resolved to '{candidate}') not found in {sample_dir}."
    )
  with candidate.open("r", encoding="utf-8") as handle:
    return json.load(handle)


def _dispatch_mock_request(
    url: str, params: dict[str, Any] | None = None, fixture_key: str | None = None
) -> dict[str, Any]:
  """Synthesizes an OLS4-compliant response from local fixtures for `--mock`."""
  params = params or {}
  if fixture_key:
    try:
      return copy.deepcopy(load_mock_data(fixture_key))
    except FileNotFoundError:
      pass

  parsed_url = urllib.parse.urlparse(url)
  path = parsed_url.path.rstrip("/")

  # 1. /v2/stats
  if path.endswith("/v2/stats") or path.endswith("/stats"):
    return copy.deepcopy(load_mock_data("stats.json"))

  # 2. /search or /suggest
  if path.endswith("/search") or path.endswith("/suggest"):
    raw_search = copy.deepcopy(load_mock_data("search_diabetes.json"))
    docs = raw_search.get("response", {}).get("docs", [])
    query = str(params.get("q", "")).strip().lower()
    ontology_filter = str(params.get("ontology", "")).strip().lower()
    type_filter = str(params.get("type", "")).strip().lower()
    exact_flag = str(params.get("exact", "")).lower() == "true"

    filtered = []
    for doc in docs:
      if ontology_filter and doc.get("ontology_name", "").lower() != ontology_filter:
        continue
      if type_filter and doc.get("type", "").lower() != type_filter:
        continue
      label = str(doc.get("label", "")).lower()
      obo_id = str(doc.get("obo_id", "")).lower()
      synonyms = [str(s).lower() for s in doc.get("synonyms", [])]
      descriptions = " ".join(doc.get("description", [])).lower()

      if not query:
        filtered.append(doc)
      elif exact_flag:
        if query == label or query == obo_id or query in synonyms:
          filtered.append(doc)
      else:
        if (
            query in label
            or query in obo_id
            or any(query in s for s in synonyms)
            or query in descriptions
        ):
          filtered.append(doc)

    # If no match in fixture for an arbitrary mock query, return all or top docs
    # only if query matches a known concept; otherwise return empty docs list.
    rows = int(params.get("rows", 10))
    start = int(params.get("start", 0))
    sliced = filtered[start : start + rows]
    return {
        "responseHeader": {"status": 0, "QTime": 1},
        "response": {
            "numFound": len(filtered),
            "start": start,
            "docs": sliced,
        },
    }

  # 3. Term / Property / Individual / Ontology routes
  unquoted_path = urllib.parse.unquote(urllib.parse.unquote(path))

  # Check if a relation sub-resource is requested on a term
  for rel in VALID_TERM_RELATIONS:
    if unquoted_path.endswith(f"/{rel}"):
      base_term_data = _resolve_mock_term_from_path(unquoted_path)
      rel_payload = base_term_data.get("relations", {}).get(rel, [])
      if rel == "graph":
        return copy.deepcopy(rel_payload) if isinstance(rel_payload, dict) else {"nodes": [], "edges": []}
      return {
          "_embedded": {"terms": copy.deepcopy(rel_payload)},
          "page": {
              "size": len(rel_payload),
              "totalElements": len(rel_payload),
              "totalPages": 1,
              "number": 0,
          },
      }

  if "/terms/roots" in unquoted_path or "/terms/preferredRoots" in unquoted_path:
    onto_data = copy.deepcopy(load_mock_data("ontology_go.json"))
    roots = onto_data.get("roots", [])
    return {
        "_embedded": {"terms": roots},
        "page": {
            "size": len(roots),
            "totalElements": len(roots),
            "totalPages": 1,
            "number": 0,
        },
    }

  if "/terms/" in unquoted_path:
    return _resolve_mock_term_from_path(unquoted_path)

  if "/properties/" in unquoted_path:
    for prop_rel in ("parents", "children", "ancestors", "descendants"):
      if unquoted_path.endswith(f"/{prop_rel}"):
        return {
            "_embedded": {
                "properties": [
                    {
                        "iri": "http://purl.obolibrary.org/obo/BFO_0000050",
                        "obo_id": "BFO:0000050",
                        "short_form": "BFO_0000050",
                        "label": "part_of",
                        "ontology_name": "ro",
                        "ontology_prefix": "RO",
                        "description": ["A core relation that holds between a part and its whole."],
                    }
                ]
            },
            "page": {"size": 1, "totalElements": 1, "totalPages": 1, "number": 0},
        }
    return {
        "iri": "http://purl.obolibrary.org/obo/BFO_0000050",
        "obo_id": "BFO:0000050",
        "short_form": "BFO_0000050",
        "label": "part_of",
        "ontology_name": "ro",
        "ontology_prefix": "RO",
        "description": ["A core relation that holds between a part and its whole."],
        "synonyms": ["part of"],
        "is_obsolete": false_bool(),
        "is_root": True,
    }

  if "/individuals/" in unquoted_path:
    for ind_rel in ("types", "alltypes", "jstree"):
      if unquoted_path.endswith(f"/{ind_rel}"):
        return {
            "_embedded": {
                "terms": [
                    {
                        "iri": "http://purl.obolibrary.org/obo/GO_0005634",
                        "obo_id": "GO:0005634",
                        "label": "nucleus",
                        "ontology_name": "go",
                    }
                ]
            },
            "page": {"size": 1, "totalElements": 1, "totalPages": 1, "number": 0},
        }
    return {
        "iri": "http://purl.obolibrary.org/obo/RO_0001901",
        "obo_id": "RO:0001901",
        "short_form": "RO_0001901",
        "label": "allen_brain_atlas_reference_individual",
        "ontology_name": "ro",
        "ontology_prefix": "RO",
        "description": ["Synthetic reference individual instance for offline validation."],
        "type": "individual",
        "is_obsolete": False,
    }

  if path.endswith("/ontologies"):
    onto_go = copy.deepcopy(load_mock_data("ontology_go.json"))
    return {
        "_embedded": {"ontologies": [onto_go]},
        "page": {"size": 1, "totalElements": 1, "totalPages": 1, "number": 0},
    }

  if "/ontologies/" in unquoted_path:
    onto_go = copy.deepcopy(load_mock_data("ontology_go.json"))
    slug = unquoted_path.rsplit("/ontologies/", 1)[-1].split("/")[0].lower()
    if slug and slug != "go":
      onto_go["ontologyId"] = slug
      onto_go["config"]["namespace"] = slug
      onto_go["config"]["preferredPrefix"] = slug.upper()
      onto_go["config"]["title"] = f"{slug.upper()} Ontology"
    return onto_go

  return copy.deepcopy(load_mock_data("go_0005634_nucleus.json"))


def false_bool() -> bool:
  return False


def _resolve_mock_term_from_path(unquoted_path: str) -> dict[str, Any]:
  """Selects the matching term fixture based on an unquoted URL path."""
  upper_path = unquoted_path.upper()
  if "DOID_9351" in upper_path or "DOID:9351" in upper_path:
    return copy.deepcopy(load_mock_data("doid_9351_diabetes.json"))
  if "GO_0006915" in upper_path or "GO:0006915" in upper_path:
    return copy.deepcopy(load_mock_data("go_0006915_apoptosis.json"))
  return copy.deepcopy(load_mock_data("go_0005634_nucleus.json"))


def make_request(
    url: str,
    params: dict[str, Any] | None = None,
    mock: bool = False,
    fixture_key: str | None = None,
) -> dict[str, Any]:
  """Executes a rate-limited HTTP GET request or returns offline mock data.

  Args:
    url: Full URL or relative path under `BASE_URL`.
    params: Optional query string parameters.
    mock: If True, bypasses network calls and loads from `sample_data/`.
    fixture_key: Optional explicit fixture identifier for mock mode.

  Returns:
    Parsed JSON response dictionary.

  Raises:
    RuntimeError: If the HTTP request fails after retries.
  """
  verify_license_guard()

  if not url.startswith(("http://", "https://")):
    full_url = f"{BASE_URL}/{url.lstrip('/')}"
  else:
    full_url = url

  if mock:
    return _dispatch_mock_request(full_url, params=params, fixture_key=fixture_key)

  clean_params: dict[str, Any] = {}
  if params:
    for k, v in params.items():
      if v is not None:
        if isinstance(v, bool):
          clean_params[k] = "true" if v else "false"
        else:
          clean_params[k] = str(v)

  if clean_params:
    query_string = urllib.parse.urlencode(clean_params)
    separator = "&" if "?" in full_url else "?"
    request_url = f"{full_url}{separator}{query_string}"
  else:
    request_url = full_url

  headers = {
      "Accept": "application/json",
      "User-Agent": USER_AGENT,
  }

  last_error: Exception | None = None
  for attempt in range(1, MAX_RETRIES + 1):
    _enforce_rate_limit()
    try:
      if HAS_POLITE_HTTP and hasattr(polite_http, "get_json"):
        return polite_http.get_json(  # type: ignore[no-any-return]
            request_url, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS
        )
      req = urllib.request.Request(request_url, headers=headers, method="GET")
      with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
        raw_bytes = resp.read()
        return json.loads(raw_bytes.decode("utf-8"))
    except urllib.error.HTTPError as exc:
      last_error = exc
      status = exc.code
      if status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        delay = float(retry_after) if (retry_after and retry_after.isdigit()) else (2 ** (attempt - 1))
        LOGGER.warning(
            "Transient HTTP %d from %s (attempt %d/%d). Retrying in %.1fs.",
            status,
            request_url,
            attempt,
            MAX_RETRIES,
            delay,
        )
        time.sleep(delay)
        continue
      raise RuntimeError(
          f"OLS4 API HTTP error {status} for URL '{request_url}': {exc.reason}"
      ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
      last_error = exc
      if attempt < MAX_RETRIES:
        delay = float(2 ** (attempt - 1))
        LOGGER.warning(
            "Request error for %s (attempt %d/%d): %s. Retrying in %.1fs.",
            request_url,
            attempt,
            MAX_RETRIES,
            exc,
            delay,
        )
        time.sleep(delay)
        continue
      raise RuntimeError(
          f"Failed to query OLS4 API at '{request_url}' after {MAX_RETRIES} attempts: {exc}. "
          "Pass --mock for offline execution."
      ) from exc

  raise RuntimeError(f"Request failed for '{request_url}': {last_error}")


def extract_embedded_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
  """Extracts `_embedded[key]` list from an OLS4 HAL JSON response."""
  if not isinstance(payload, dict):
    return []
  embedded = payload.get("_embedded")
  if isinstance(embedded, dict) and isinstance(embedded.get(key), list):
    return list(embedded[key])
  if isinstance(payload.get(key), list):
    return list(payload[key])
  return []


def write_json_output(data: Any, output_path: str | Path) -> Path:
  """Writes data as formatted UTF-8 JSON to `output_path`."""
  target = Path(output_path)
  target.parent.mkdir(parents=True, exist_ok=True)
  with target.open("w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
  return target
