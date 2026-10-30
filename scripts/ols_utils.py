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
"""Shared utilities, and rate-limited HTTP transport for EMBL-EBI OLS4."""

from __future__ import annotations

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


EXAMPLE_TERM_FILES: tuple[str, ...] = (
    "go_0005634_nucleus.json",
    "doid_9351_diabetes.json",
    "go_0006915_apoptosis.json",
)

EXAMPLE_ONTOLOGY_FILES: dict[str, str] = {
    "go": "ontology_go.json",
}


def load_example_data(filename: str) -> dict[str, Any]:
  """Loads a bundled example JSON file from `sample_data/`.

  These files are only used to populate the dashboard's "Examples" group.
  They are never substituted for live OLS4 API responses or uploaded data.

  Args:
    filename: File basename inside `sample_data/` (e.g. `go_0005634_nucleus.json`).

  Returns:
    Parsed JSON dictionary.

  Raises:
    FileNotFoundError: If the example file does not exist.
  """
  candidate = get_skill_root() / "sample_data" / filename
  if not candidate.is_file():
    raise FileNotFoundError(f"Example data file not found: {candidate}")
  with candidate.open("r", encoding="utf-8") as handle:
    return json.load(handle)


def _http_get(request_url: str, headers: dict[str, str]) -> dict[str, Any]:
  """Performs a single HTTP GET against the live API and parses JSON."""
  if HAS_POLITE_HTTP and hasattr(polite_http, "get_json"):
    return polite_http.get_json(  # type: ignore[no-any-return]
        request_url, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS
    )
  req = urllib.request.Request(request_url, headers=headers, method="GET")
  with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
    raw_bytes = resp.read()
    return json.loads(raw_bytes.decode("utf-8"))


def make_request(
    url: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """Executes a rate-limited, retried HTTP GET request against the OLS4 API.

  Args:
    url: Full URL or relative path under `BASE_URL`.
    params: Optional query string parameters.

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
      return _http_get(request_url, headers)
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
          "Check network access to the EMBL-EBI OLS4 API."
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
