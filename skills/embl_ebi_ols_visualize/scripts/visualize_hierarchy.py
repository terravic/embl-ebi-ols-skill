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
"""Transforms raw OLS4 term and relation payloads into normalized DAG and Tree structures."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

import ols_utils  # pylint: disable=wrong-import-position

EDGE_STYLE_MAP: dict[str, dict[str, Any]] = {
    "subClassOf": {
        "is_hierarchical": False,
        "stroke": "#0D9488",
        "color": "#0D9488",
        "pattern": "solid",
        "dasharray": "none",
        "category": "taxonomic",
        "display_label": "is_a (subClassOf)",
    },
    "part_of": {
        "is_hierarchical": True,
        "stroke": "#D97706",
        "color": "#D97706",
        "pattern": "dashed",
        "dasharray": "6,4",
        "category": "partonomic",
        "display_label": "part_of",
    },
    "develops_from": {
        "is_hierarchical": True,
        "stroke": "#059669",
        "color": "#059669",
        "pattern": "dashed",
        "dasharray": "8,4",
        "category": "developmental",
        "display_label": "develops_from",
    },
    "derives_from": {
        "is_hierarchical": True,
        "stroke": "#059669",
        "color": "#059669",
        "pattern": "dashed",
        "dasharray": "8,4",
        "category": "developmental",
        "display_label": "derives_from",
    },
    "occurs_in": {
        "is_hierarchical": True,
        "stroke": "#4F46E5",
        "color": "#4F46E5",
        "pattern": "dotted",
        "dasharray": "3,3",
        "category": "spatial",
        "display_label": "occurs_in",
    },
    "located_in": {
        "is_hierarchical": True,
        "stroke": "#4F46E5",
        "color": "#4F46E5",
        "pattern": "dotted",
        "dasharray": "3,3",
        "category": "spatial",
        "display_label": "located_in",
    },
    "regulates": {
        "is_hierarchical": True,
        "stroke": "#E11D48",
        "color": "#E11D48",
        "pattern": "dotted",
        "dasharray": "4,3",
        "category": "regulatory",
        "display_label": "regulates",
    },
    # OLS4 `hierarchicalParents`/`hierarchicalChildren` items that do not state
    # which hierarchical property links them (and no `/graph` edge resolves it).
    "hierarchical": {
        "is_hierarchical": True,
        "stroke": "#D97706",
        "color": "#D97706",
        "pattern": "dashed",
        "dasharray": "2,3",
        "category": "hierarchical",
        "display_label": "hierarchical",
    },
}

# OLS4 `/graph` edges are serialized subject -> object (e.g. child subClassOf
# parent). These relations point from the whole/parent to the part/child, so
# they are kept as-is instead of being reversed for top-down display.
INVERSE_GRAPH_RELATIONS: frozenset[str] = frozenset({
    "has_part",
    "bfo_0000051",
})

EXTERNAL_DB_URL_TEMPLATES: dict[str, str] = {
    "MESH": "https://meshb.nlm.nih.gov/record/ui?ui={id}",
    "MSH": "https://meshb.nlm.nih.gov/record/ui?ui={id}",
    "OMIM": "https://www.omim.org/entry/{id}",
    "MIM": "https://www.omim.org/entry/{id}",
    "PMID": "https://pubmed.ncbi.nlm.nih.gov/{id}/",
    "WIKIPEDIA": "https://en.wikipedia.org/wiki/{id}",
    "REACTOME": "https://reactome.org/content/detail/{id}",
    "ICD10CM": "https://icd.who.int/browse10/2019/en#/{id}",
    "ICD10": "https://icd.who.int/browse10/2019/en#/{id}",
    "UMLS": "https://uts.nlm.nih.gov/uts/umls/concept/{id}",
    "UMLS_CUI": "https://uts.nlm.nih.gov/uts/umls/concept/{id}",
    "SNOMEDCT_US": "https://browser.ihtsdotools.org/?perspective=full&conceptId1={id}",
    "MEDDRA": "https://www.meddra.org/",
}


def canonical_node_id(item: dict[str, Any] | str) -> str | None:
  """Extracts a canonical OBO ID (or IRI) from a term object or string.

  Returns None when the item carries no usable identifier, so callers can skip
  it instead of inventing a placeholder ID.
  """
  if isinstance(item, str):
    return (ols_utils.iri_to_obo_id(item) or item.strip()) or None
  if not isinstance(item, dict):
    return None
  obo_id = item.get("obo_id")
  if obo_id and isinstance(obo_id, str) and obo_id.strip():
    return obo_id.strip()
  short_form = item.get("short_form")
  if short_form and isinstance(short_form, str) and "_" in short_form:
    prefix, local = short_form.split("_", 1)
    if prefix.isalpha():
      return f"{prefix.upper()}:{local}"
  iri = item.get("iri") or item.get("id")
  if iri and isinstance(iri, str) and iri.strip():
    return ols_utils.iri_to_obo_id(iri) or iri.strip()
  return None


def normalize_relation_type(raw_rel: str | None) -> str:
  """Normalizes an OLS4 edge label or property URI to a semantic relation type."""
  if not raw_rel:
    return "hierarchical"
  cleaned = raw_rel.strip()
  lower = cleaned.lower().replace(" ", "_")
  if lower in ("subclassof", "is_a", "is-a", "rdfs:subclassof") or cleaned.endswith(
      "#subClassOf"
  ):
    return "subClassOf"
  if "bfo_0000050" in lower or lower == "part_of":
    return "part_of"
  if "ro_0002202" in lower or "develops_from" in lower:
    return "develops_from"
  if "ro_0001000" in lower or "derives_from" in lower:
    return "derives_from"
  if "bfo_0000066" in lower or "occurs_in" in lower:
    return "occurs_in"
  if "ro_0001025" in lower or "located_in" in lower:
    return "located_in"
  if (
      "ro_0002211" in lower
      or "ro_0002212" in lower
      or "ro_0002213" in lower
      or "regulates" in lower
  ):
    return "regulates"
  return cleaned


def classify_edge_style(relation_type: str) -> dict[str, Any]:
  """Returns semantic classification and visual style metadata for a relation."""
  norm = normalize_relation_type(relation_type)
  if norm in EDGE_STYLE_MAP:
    return dict(EDGE_STYLE_MAP[norm])
  return {
      "is_hierarchical": True,
      "stroke": "#78716C",
      "color": "#78716C",
      "pattern": "dotted",
      "dasharray": "4,3",
      "category": "other",
      "display_label": norm,
  }


def extract_synonyms(term_obj: dict[str, Any]) -> list[dict[str, Any]]:
  """Extracts structured synonyms with scope (`EXACT`, `BROAD`, `NARROW`, `RELATED`)."""
  structured: list[dict[str, Any]] = []
  seen: set[tuple[str, str]] = set()

  obo_synonyms = term_obj.get("obo_synonym")
  if isinstance(obo_synonyms, list):
    for syn in obo_synonyms:
      if not isinstance(syn, dict):
        continue
      name = str(syn.get("name", "")).strip()
      if not name:
        continue
      raw_scope = str(syn.get("scope") or "").upper()
      if not raw_scope:
        scope = ""
      elif "EXACT" in raw_scope:
        scope = "EXACT"
      elif "BROAD" in raw_scope:
        scope = "BROAD"
      elif "NARROW" in raw_scope:
        scope = "NARROW"
      else:
        scope = "RELATED"
      xref_list: list[str] = []
      for xr in syn.get("xrefs") or []:
        if isinstance(xr, dict):
          db = xr.get("database") or ""
          xid = xr.get("id") or ""
          xref_list.append(f"{db}:{xid}".strip(":"))
        elif isinstance(xr, str):
          xref_list.append(xr)
      key = (name.lower(), scope)
      if key not in seen:
        seen.add(key)
        structured.append({
            "name": name,
            "scope": scope,
            "type": syn.get("type"),
            "xrefs": xref_list,
        })

  plain_synonyms = term_obj.get("synonyms")
  if isinstance(plain_synonyms, list):
    for syn_str in plain_synonyms:
      name = str(syn_str).strip()
      if not name:
        continue
      if not any(existing["name"].lower() == name.lower() for existing in structured):
        # Plain `synonyms` strings carry no scope in the OLS4 response.
        structured.append({
            "name": name,
            "scope": "",
            "type": None,
            "xrefs": [],
        })

  return structured


def extract_xrefs(term_obj: dict[str, Any]) -> list[dict[str, Any]]:
  """Extracts cross-references (`obo_xref`) with resolved external URLs."""
  xrefs: list[dict[str, Any]] = []
  raw_xrefs = term_obj.get("obo_xref")
  if not isinstance(raw_xrefs, list):
    return xrefs

  for item in raw_xrefs:
    if not isinstance(item, dict):
      continue
    database = str(item.get("database") or "").strip()
    xid = str(item.get("id") or "").strip()
    if not database and not xid:
      continue
    url = item.get("url")
    if not url and database.upper() in EXTERNAL_DB_URL_TEMPLATES and xid:
      url = EXTERNAL_DB_URL_TEMPLATES[database.upper()].format(id=xid)
    xrefs.append({
        "database": database,
        "id": xid,
        "description": item.get("description") or "",
        "url": url or "",
    })
  return xrefs


def _extract_definition(term_obj: dict[str, Any]) -> str:
  """Extracts the primary text definition from an OLS4 term object."""
  desc = term_obj.get("description")
  if isinstance(desc, list) and desc:
    return str(desc[0]).strip()
  if isinstance(desc, str) and desc.strip():
    return desc.strip()
  obo_def = term_obj.get("obo_definition_citation")
  if isinstance(obo_def, list) and obo_def and isinstance(obo_def[0], dict):
    return str(obo_def[0].get("definition") or "").strip()
  return ""


def _extract_comments(term_obj: dict[str, Any]) -> list[str]:
  """Extracts curation comments from `annotation.comment`."""
  ann = term_obj.get("annotation")
  if isinstance(ann, dict):
    comments = ann.get("comment")
    if isinstance(comments, list):
      return [str(c).strip() for c in comments if str(c).strip()]
    if isinstance(comments, str) and comments.strip():
      return [comments.strip()]
  return []


def build_hierarchy_payload(
    term_data: dict[str, Any],
    title: str | None = None,
) -> dict[str, Any]:
  """Transforms a raw term and relation dictionary into normalized DAG & Tree JSON.

  Args:
    term_data: Term payload produced by `get_term.py` (or raw graph JSON).
    title: Optional custom dashboard title.

  Returns:
    Normalized hierarchy payload matching `references/dashboard_schema.md`.
  """
  if not isinstance(term_data, dict):
    raise ValueError("term_data must be a JSON object dictionary.")

  target_id = canonical_node_id(term_data)
  if not target_id:
    raise ValueError(
        "Term payload has no identifier (obo_id, short_form, or iri)."
    )
  target_label = str(term_data.get("label") or target_id)
  target_iri = str(
      term_data.get("iri")
      or (ols_utils.obo_id_to_iri(target_id) if ":" in target_id else target_id)
  )
  ontology_slug = str(
      term_data.get("ontology_name")
      or (target_id.split(":", 1)[0].lower() if ":" in target_id else "")
  )
  ontology_prefix = str(
      term_data.get("ontology_prefix")
      or (target_id.split(":", 1)[0].upper() if ":" in target_id else ontology_slug.upper())
  )

  nodes_by_id: dict[str, dict[str, Any]] = {}
  iri_to_id: dict[str, str] = {}

  def register_node(raw: dict[str, Any], is_target: bool = False) -> str | None:
    nid = canonical_node_id(raw)
    if not nid:
      return None
    n_iri = str(raw.get("iri") or (ols_utils.obo_id_to_iri(nid) if ":" in nid else nid))
    iri_to_id[n_iri] = nid
    iri_to_id[nid] = nid

    existing = nodes_by_id.get(nid)
    label = str(raw.get("label") or (existing["label"] if existing else nid))
    defn = _extract_definition(raw) or (existing["definition"] if existing else "")
    onto_pref = str(
        raw.get("ontology_prefix")
        or (existing["ontology"] if existing else "")
        or (nid.split(":", 1)[0].upper() if ":" in nid else "")
    )
    is_root = bool(raw.get("is_root", False)) or (
        existing["is_root"] if existing else False
    )
    is_obsolete = bool(raw.get("is_obsolete", False)) or (
        existing["is_obsolete"] if existing else False
    )
    syns = extract_synonyms(raw) or (existing["synonyms"] if existing else [])
    xrs = extract_xrefs(raw) or (existing["xrefs"] if existing else [])
    comments = _extract_comments(raw) or (existing["comments"] if existing else [])
    subsets = list(raw.get("in_subset") or (existing["subsets"] if existing else []))

    nodes_by_id[nid] = {
        "id": nid,
        "iri": n_iri,
        "label": label,
        "ontology": onto_pref,
        "definition": defn,
        "is_target": bool(is_target or (existing and existing["is_target"])),
        "is_root": is_root,
        "is_obsolete": is_obsolete,
        "depth": 0,
        "on_root_path": False,
        "synonyms": syns,
        "xrefs": xrs,
        "comments": comments,
        "subsets": subsets,
    }
    return nid

  register_node(term_data, is_target=True)

  relations = term_data.get("relations")
  if not isinstance(relations, dict):
    relations = {}

  def rel_list(key: str) -> list[dict[str, Any]]:
    items = relations.get(key) or term_data.get(key) or []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

  # Register all nodes from relation lists
  for rel_key in (
      "parents",
      "children",
      "ancestors",
      "descendants",
      "hierarchicalParents",
      "hierarchicalChildren",
      "hierarchicalAncestors",
      "hierarchicalDescendants",
  ):
    for item in rel_list(rel_key):
      register_node(item)

  # Register nodes from embedded `graph` block if present
  graph_block = relations.get("graph") or term_data.get("graph")
  if isinstance(graph_block, dict):
    for gnode in graph_block.get("nodes") or []:
      if isinstance(gnode, dict):
        register_node(gnode)

  # Collect and deduplicate directed edges (parent/whole -> child/part)
  edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
  edge_pairs: set[tuple[str, str]] = set()

  def resolve_id(raw: str) -> str | None:
    if not raw:
      return None
    return iri_to_id.get(raw) or canonical_node_id(raw)

  def add_edge(src_id: str | None, tgt_id: str | None, raw_type: str | None) -> None:
    if not src_id or not tgt_id or src_id == tgt_id:
      return
    if src_id not in nodes_by_id or tgt_id not in nodes_by_id:
      return
    rel_type = normalize_relation_type(raw_type)
    # An untyped hierarchical link adds nothing if a typed edge already exists.
    if rel_type == "hierarchical" and (src_id, tgt_id) in edge_pairs:
      return
    style_meta = classify_edge_style(rel_type)
    key = (src_id, tgt_id, rel_type)
    if key not in edges_by_key:
      edge_pairs.add((src_id, tgt_id))
      edges_by_key[key] = {
          "id": f"{src_id}->{tgt_id}:{rel_type}",
          "source": src_id,
          "target": tgt_id,
          "type": rel_type,
          "label": style_meta["display_label"],
          "is_hierarchical": style_meta["is_hierarchical"],
          "on_root_path": False,
          "style": {
              "stroke": style_meta["stroke"],
              "color": style_meta["color"],
              "pattern": style_meta["pattern"],
              "dasharray": style_meta["dasharray"],
              "category": style_meta["category"],
          },
      }

  # 1. `/graph` edges. OLS4 serializes them subject -> object (child -> parent
  # for subClassOf / part_of). Reverse them for top-down display, except for
  # relations that already point whole -> part (e.g. has_part).
  if isinstance(graph_block, dict):
    for gedge in graph_block.get("edges") or []:
      if not isinstance(gedge, dict):
        continue
      raw_label = gedge.get("label") or gedge.get("uri")
      if not raw_label:
        continue
      sid = resolve_id(str(gedge.get("source") or ""))
      tid = resolve_id(str(gedge.get("target") or ""))
      label_key = str(raw_label).strip().lower().replace(" ", "_")
      uri_key = str(gedge.get("uri") or "").rsplit("/", 1)[-1].lower()
      if label_key in INVERSE_GRAPH_RELATIONS or uri_key in INVERSE_GRAPH_RELATIONS:
        add_edge(sid, tid, str(raw_label))
      else:
        add_edge(tid, sid, str(raw_label))

  # 2. `/parents` and `/children` are OLS4's is-a (subClassOf) relations.
  direct_parent_ids: set[str] = set()
  for p_item in rel_list("parents"):
    pid = canonical_node_id(p_item)
    if pid:
      direct_parent_ids.add(pid)
      add_edge(pid, target_id, p_item.get("relation_type") or "subClassOf")

  direct_child_ids: set[str] = set()
  for c_item in rel_list("children"):
    cid = canonical_node_id(c_item)
    if cid:
      direct_child_ids.add(cid)
      add_edge(target_id, cid, c_item.get("relation_type") or "subClassOf")

  # 3. `/hierarchicalParents` / `/hierarchicalChildren` include is-a plus other
  # hierarchical properties (e.g. part_of). OLS4 does not say which one, so the
  # edge is typed from the item itself, else the is-a lists, else "hierarchical".
  for hp_item in rel_list("hierarchicalParents"):
    hpid = canonical_node_id(hp_item)
    rel_t = hp_item.get("relation_type") or (
        "subClassOf" if hpid in direct_parent_ids else None
    )
    add_edge(hpid, target_id, rel_t)

  for hc_item in rel_list("hierarchicalChildren"):
    hcid = canonical_node_id(hc_item)
    rel_t = hc_item.get("relation_type") or (
        "subClassOf" if hcid in direct_child_ids else None
    )
    add_edge(target_id, hcid, rel_t)

  # 4. Lineage records (`get_term.py --lineage`): each ancestor's own parents.
  for rec in relations.get("lineage") or []:
    if not isinstance(rec, dict):
      continue
    child_id = resolve_id(str(rec.get("iri") or "")) or canonical_node_id(rec)
    isa_ids: set[str] = set()
    for p_item in rec.get("parents") or []:
      if isinstance(p_item, dict):
        pid = canonical_node_id(p_item)
        if pid:
          isa_ids.add(pid)
          add_edge(pid, child_id, p_item.get("relation_type") or "subClassOf")
    for hp_item in rec.get("hierarchicalParents") or []:
      if isinstance(hp_item, dict):
        hpid = canonical_node_id(hp_item)
        rel_t = hp_item.get("relation_type") or (
            "subClassOf" if hpid in isa_ids else None
        )
        add_edge(hpid, child_id, rel_t)

  # Ancestors/descendants returned without connecting edges (no `/graph` data)
  # are not wired into an invented lineage; they are reported as unconnected.
  connected_ids: set[str] = {target_id}
  for (s, t, _) in edges_by_key:
    connected_ids.add(s)
    connected_ids.add(t)
  unconnected_ids = sorted(nid for nid in nodes_by_id if nid not in connected_ids)
  for nid in unconnected_ids:
    del nodes_by_id[nid]

  incoming_map: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}
  outgoing_map: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}
  for (s, t, _) in edges_by_key:
    outgoing_map[s].append(t)
    incoming_map[t].append(s)

  # Compute relative topological depth from `target_id` via bidirectional BFS
  nodes_by_id[target_id]["depth"] = 0
  visited_up: set[str] = {target_id}
  queue_up: deque[tuple[str, int]] = deque([(target_id, 0)])
  while queue_up:
    curr, d = queue_up.popleft()
    for parent_id in incoming_map.get(curr, []):
      if parent_id not in visited_up:
        visited_up.add(parent_id)
        nodes_by_id[parent_id]["depth"] = d - 1
        queue_up.append((parent_id, d - 1))

  visited_down: set[str] = {target_id}
  queue_down: deque[tuple[str, int]] = deque([(target_id, 0)])
  while queue_down:
    curr, d = queue_down.popleft()
    for child_id in outgoing_map.get(curr, []):
      if child_id not in visited_down and child_id not in visited_up:
        visited_down.add(child_id)
        nodes_by_id[child_id]["depth"] = d + 1
        queue_down.append((child_id, d + 1))

  # Top-level nodes of this subgraph: no incoming edge. The `is_root` flag is
  # left exactly as reported by OLS4 (ontology roots only).
  top_ids = [nid for nid in nodes_by_id if not incoming_map.get(nid)]
  if not top_ids:
    # Fully cyclic subgraph: start traversal from the target term.
    top_ids = [target_id]

  # Trace shortest paths from each top-level ancestor down to `target_id`
  root_paths: list[list[str]] = []
  root_path_nodes: set[str] = {target_id}
  root_path_pairs: set[tuple[str, str]] = set()

  for rid in top_ids:
    if rid == target_id:
      root_paths.append([target_id])
      continue
    bfs_q: deque[list[str]] = deque([[rid]])
    visited_bfs: set[str] = {rid}
    found_path: list[str] | None = None
    while bfs_q:
      path = bfs_q.popleft()
      last = path[-1]
      if last == target_id:
        found_path = path
        break
      for nxt in outgoing_map.get(last, []):
        if nxt not in visited_bfs:
          visited_bfs.add(nxt)
          bfs_q.append(path + [nxt])
    if found_path:
      root_paths.append(found_path)
      root_path_nodes.update(found_path)
      for i in range(len(found_path) - 1):
        root_path_pairs.add((found_path[i], found_path[i + 1]))

  for nid in root_path_nodes:
    if nid in nodes_by_id:
      nodes_by_id[nid]["on_root_path"] = True

  for edge in edges_by_key.values():
    if (edge["source"], edge["target"]) in root_path_pairs:
      edge["on_root_path"] = True

  # Build the hierarchical forest for the collapsible D3 tree view
  edge_type_lookup: dict[tuple[str, str], str] = {}
  for (s, t, rtype) in edges_by_key:
    if (s, t) not in edge_type_lookup or rtype == "subClassOf":
      edge_type_lookup[(s, t)] = rtype

  def build_tree_node(
      nid: str,
      rel_to_parent: str,
      path_visited: frozenset[str],
      current_depth: int,
  ) -> dict[str, Any]:
    n_meta = nodes_by_id[nid]
    children_nodes: list[dict[str, Any]] = []
    if current_depth < 12:
      seen_child_ids: list[str] = []
      for cid in outgoing_map.get(nid, []):
        if cid not in seen_child_ids and cid not in path_visited:
          seen_child_ids.append(cid)
      for cid in sorted(seen_child_ids, key=lambda x: nodes_by_id[x]["label"].lower()):
        children_nodes.append(
            build_tree_node(
                cid,
                edge_type_lookup[(nid, cid)],
                path_visited | {cid},
                current_depth + 1,
            )
        )
    return {
        "id": nid,
        "name": f"{n_meta['label']} ({nid})",
        "label": n_meta["label"],
        "ontology": n_meta["ontology"],
        "definition": n_meta["definition"],
        "relation_to_parent": rel_to_parent,
        "is_target": n_meta["is_target"],
        "is_root": n_meta["is_root"],
        "is_obsolete": n_meta["is_obsolete"],
        "on_root_path": n_meta["on_root_path"],
        "depth": n_meta["depth"],
        "children": children_nodes,
    }

  sorted_tops = sorted(top_ids, key=lambda x: nodes_by_id[x]["label"].lower())
  trees = [build_tree_node(rid, "root", frozenset({rid}), 0) for rid in sorted_tops]

  # Populate direct parents and direct children on every node for inspector navigation
  for nid, n_meta in nodes_by_id.items():
    p_list: list[dict[str, str]] = []
    seen_p: set[str] = set()
    for pid in incoming_map.get(nid, []):
      if pid not in seen_p and pid in nodes_by_id:
        seen_p.add(pid)
        p_list.append({
            "id": pid,
            "label": nodes_by_id[pid]["label"],
            "relation": edge_type_lookup[(pid, nid)],
        })
    c_list: list[dict[str, str]] = []
    seen_c: set[str] = set()
    for cid in outgoing_map.get(nid, []):
      if cid not in seen_c and cid in nodes_by_id:
        seen_c.add(cid)
        c_list.append({
            "id": cid,
            "label": nodes_by_id[cid]["label"],
            "relation": edge_type_lookup[(nid, cid)],
        })
    n_meta["parents"] = p_list
    n_meta["children"] = c_list

  target_node = nodes_by_id[target_id]
  relation_counts: dict[str, int] = {}
  for edge in edges_by_key.values():
    rtype = edge["type"]
    relation_counts[rtype] = relation_counts.get(rtype, 0) + 1

  nodes_list = sorted(
      nodes_by_id.values(), key=lambda x: (x["depth"], x["label"].lower())
  )
  edges_list = list(edges_by_key.values())

  ancestor_count = sum(1 for n in nodes_list if n["depth"] < 0)
  descendant_count = sum(1 for n in nodes_list if n["depth"] > 0)

  dashboard_title = (
      title
      or f"EMBL-EBI OLS Hierarchy Explorer: {target_label} ({target_id})"
  )

  raw_relation_counts: dict[str, int] = {}
  for rel_k in (
      "parents",
      "children",
      "ancestors",
      "descendants",
      "hierarchicalParents",
      "hierarchicalChildren",
      "hierarchicalAncestors",
      "hierarchicalDescendants",
  ):
    rel_arr = relations.get(rel_k) or term_data.get(rel_k)
    if isinstance(rel_arr, list):
      raw_relation_counts[rel_k] = len(rel_arr)
  if isinstance(graph_block, dict):
    raw_relation_counts["graph_nodes"] = len(graph_block.get("nodes") or [])
    raw_relation_counts["graph_edges"] = len(graph_block.get("edges") or [])

  depths = [n["depth"] for n in nodes_list] or [0]
  double_encoded = ""
  try:
    double_encoded = ols_utils.double_encode_iri(target_iri)
  except ValueError:
    double_encoded = ""

  return {
      "title": dashboard_title,
      "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      "input_summary": {
          "obo_id": target_id,
          "iri": target_iri,
          "double_encoded_iri": double_encoded,
          "ontology": ontology_slug,
          "ontology_prefix": ontology_prefix,
          "api_endpoint": f"{ols_utils.BASE_URL}/ontologies/{ontology_slug}/terms/{double_encoded}",
          "raw_synonym_count": len(term_data.get("synonyms") or []) + len(term_data.get("obo_synonym") or []),
          "raw_xref_count": len(term_data.get("obo_xref") or []),
          "raw_relation_counts": raw_relation_counts,
      },
      "processing_summary": {
          "normalized_nodes": len(nodes_list),
          "deduplicated_edges": len(edges_list),
          "min_depth": min(depths),
          "max_depth": max(depths),
          "depth_span": (max(depths) - min(depths)) + 1,
          "shortest_root_paths": len(root_paths),
          "unconnected_nodes": len(unconnected_ids),
          "scoped_synonyms": len(target_node["synonyms"]),
          "resolved_xrefs": len(target_node["xrefs"]),
          "relation_breakdown": relation_counts,
      },
      "target_term": {
          "id": target_id,
          "iri": target_iri,
          "short_form": term_data.get("short_form") or target_id.replace(":", "_"),
          "label": target_label,
          "ontology": ontology_slug,
          "ontology_prefix": ontology_prefix,
          "definition": target_node["definition"],
          "comments": target_node["comments"],
          "is_obsolete": target_node["is_obsolete"],
          "term_replaced_by": term_data.get("term_replaced_by"),
          "is_defining_ontology": term_data.get("is_defining_ontology"),
          "is_root": target_node["is_root"],
          "subsets": target_node["subsets"],
          "synonyms": target_node["synonyms"],
          "xrefs": target_node["xrefs"],
          "parents": target_node["parents"],
          "children": target_node["children"],
      },
      "nodes": nodes_list,
      "edges": edges_list,
      "trees": trees,
      "root_paths": root_paths,
      "metrics": {
          "node_count": len(nodes_list),
          "edge_count": len(edges_list),
          "ancestor_count": ancestor_count,
          "descendant_count": descendant_count,
          "direct_parent_count": len(target_node["parents"]),
          "direct_child_count": len(target_node["children"]),
          "relation_counts": relation_counts,
      },
      "citations": [
          {"id": "ols4_2025", "text": ols_utils.PRIMARY_CITATION},
          {"id": "ols_2015", "text": ols_utils.ORIGINAL_CITATION},
      ],
      "disclaimer": ols_utils.SCIENTIFIC_DISCLAIMER,
  }


def build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `visualize_hierarchy.py`."""
  parser = argparse.ArgumentParser(
      description="Transform OLS4 term and relation JSON into normalized DAG and Tree structures."
  )
  parser.add_argument(
      "-i",
      "--input",
      "--term_json",
      dest="input_path",
      required=True,
      help="Path to input term JSON file generated by get_term.py.",
  )
  parser.add_argument(
      "--title",
      help="Optional custom title for the hierarchy payload.",
  )
  parser.add_argument(
      "-o",
      "--output",
      required=True,
      help="Output JSON file path for the normalized hierarchy graph.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint for `visualize_hierarchy.py`."""
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    in_path = Path(args.input_path)
    if not in_path.is_file():
      raise FileNotFoundError(f"Input term JSON file not found: {in_path}")
    with in_path.open("r", encoding="utf-8") as handle:
      raw_term = json.load(handle)

    payload = build_hierarchy_payload(raw_term, title=args.title)
    out_path = ols_utils.write_json_output(payload, args.output)
    metrics = payload["metrics"]
    print(
        f"Hierarchy graph compiled for {payload['target_term']['label']} "
        f"({payload['target_term']['id']}): {metrics['node_count']} nodes, "
        f"{metrics['edge_count']} edges. Saved to {out_path}."
    )
    return 0
  except Exception as exc:  # pylint: disable=broad-except
    ols_utils.LOGGER.error("visualize_hierarchy failed: %s", exc)
    return 1


if __name__ == "__main__":
  sys.exit(main())
