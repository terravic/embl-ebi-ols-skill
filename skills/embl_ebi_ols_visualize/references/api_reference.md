# EMBL-EBI Ontology Lookup Service (OLS4) REST API Reference

## Base URL and Transport

- **Base URL**: `https://www.ebi.ac.uk/ols4/api`
- **Protocol**: HTTPS (`GET` requests returning `application/json` or `application/hal+json`)
- **Rate Limit**: Maximum 5.0 requests per second (minimum 0.2 seconds between consecutive requests) per EMBL-EBI Terms of Use (`https://www.ebi.ac.uk/about/terms-of-use/`).
- **API Documentation**: `https://www.ebi.ac.uk/ols4/api-docs`

---

## IRI Canonicalization and Double URL-Encoding

Most biomedical ontologies indexed in OLS4 follow the Open Biological and Biomedical Ontology (OBO) Foundry IRI pattern:

- **OBO ID**: `PREFIX:LOCAL_ID` (for example, `GO:0005634` or `DOID:9351`)
- **Canonical IRI**: `http://purl.obolibrary.org/obo/PREFIX_LOCAL_ID` (for example, `http://purl.obolibrary.org/obo/GO_0005634`)

When passing a canonical IRI as a path segment in OLS4 Spring Boot REST endpoints, the IRI must be **double URL-encoded** so that embedded forward slashes (`%2F`) are not decoded prematurely by the HTTP servlet router:

1. Single encode: `http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2FGO_0005634`
2. Double encode: `http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FGO_0005634`

---

## Core REST Endpoints

### 1. Full-Text Search (`/search`)

- **Path**: `GET /search`
- **Query Parameters**:
  - `q` (required): Search keyword or phrase (e.g., `diabetes`, `nucleus`, `apoptosis`).
  - `ontology` (optional): Comma-separated ontology slugs (e.g., `go`, `doid,hp`).
  - `type` (optional): Entity type filter (`class`, `property`, `individual`, `ontology`).
  - `exact` (optional): Boolean (`true` / `false`) restricting to exact label or synonym matches.
  - `isDefiningOntology` (optional): Boolean (`true` / `false`) restricting results to terms defined natively by the ontology (`--defining`).
  - `obsoletes` (optional): Boolean (`true` / `false`) to include deprecated terms (`--obsolete`).
  - `local` (optional): Boolean (`true` / `false`) restricting to locally defined terms (`--local`).
  - `childrenOf` (optional): IRI of parent term to restrict search to direct/transitive children.
  - `allChildrenOf` (optional): IRI of parent term to restrict search across all hierarchical relations (`is-a`, `part_of`, etc.).
  - `rows` (optional): Number of records per page (default: `10`).
  - `start` (optional): Zero-based pagination offset (default: `0`).
- **Response Structure**:
  ```json
  {
    "response": {
      "numFound": 1,
      "start": 0,
      "docs": [
        {
          "id": "go:class:http://purl.obolibrary.org/obo/GO_0005634",
          "iri": "http://purl.obolibrary.org/obo/GO_0005634",
          "short_form": "GO_0005634",
          "obo_id": "GO:0005634",
          "label": "nucleus",
          "ontology_name": "go",
          "ontology_prefix": "GO",
          "description": ["A membrane-bounded organelle of eukaryotic cells..."],
          "type": "class",
          "is_defining_ontology": true
        }
      ]
    }
  }
  ```

### 2. Autocomplete Suggestions (`/suggest`)

- **Path**: `GET /suggest`
- **Query Parameters**:
  - `q` (required): Prefix string for low-latency autocomplete.
  - `ontology` (optional): Ontology filter slug.
  - `rows` (optional): Number of suggestions to return (default: `10`).
  - `start` (optional): Zero-based pagination offset (default: `0`).

### 3. Term Details and Hierarchical Relations (`/ontologies/{ontology}/terms/{double_encoded_iri}`)

- **Primary Term Path**: `GET /ontologies/{ontology}/terms/{double_encoded_iri}`
- **Root Term Listing**: `GET /ontologies/{ontology}/terms/roots` or `GET /ontologies/{ontology}/terms/preferredRoots`
- **Hierarchical Traversal Sub-Endpoints**:
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/parents`: Direct taxonomic (`subClassOf`) parents.
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/children`: Direct taxonomic (`subClassOf`) children.
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/ancestors`: Transitive closure of taxonomic parents up to ontology roots.
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/descendants`: Transitive closure of taxonomic children.
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/hierarchicalParents`: Direct parents including taxonomic (`subClassOf`) and partonomic (`part_of`, `develops_from`) relations.
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/hierarchicalChildren`: Direct children across taxonomic and partonomic relations.
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/hierarchicalAncestors`: All transitive hierarchical ancestors.
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/hierarchicalDescendants`: All transitive hierarchical descendants.
  - `GET /ontologies/{ontology}/terms/{double_encoded_iri}/graph`: Precomputed JSON node-link graph representation of the term neighborhood.

### 4. Property Endpoints (`/ontologies/{ontology}/properties/{double_encoded_iri}`)

- **Path**: `GET /ontologies/{ontology}/properties/{double_encoded_iri}`
- **Sub-Relations**: `/parents`, `/children`, `/ancestors`, `/descendants`

### 5. Individual Endpoints (`/ontologies/{ontology}/individuals/{double_encoded_iri}`)

- **Path**: `GET /ontologies/{ontology}/individuals/{double_encoded_iri}`
- **Sub-Relations**: `/types`, `/alltypes`, `/jstree`

### 6. Ontology Metadata (`/ontologies` and `/ontologies/{ontology}`)

- **List All Ontologies**: `GET /ontologies?page={page}&size={size}`
- **Single Ontology Metadata**: `GET /ontologies/{ontology}`

### 7. Repository Statistics (`/v2/stats`)

- **Path**: `GET /v2/stats`
- **Returns**: Global counts across the OLS4 index (`numberOfOntologies`, `numberOfClasses`, `numberOfProperties`, `numberOfIndividuals`, `lastModified`).
