PRAGMA foreign_keys = OFF;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

DROP TABLE IF EXISTS node_attribute_kv;
DROP TABLE IF EXISTS node_provenance_sources;
DROP TABLE IF EXISTS edge_attribute_kv;
DROP TABLE IF EXISTS edge_provenance_sources;
DROP TABLE IF EXISTS stage4_matches;
DROP TABLE IF EXISTS stage5_findings;
DROP TABLE IF EXISTS stage5_metrics;
DROP TABLE IF EXISTS vector_provenance_sources;
DROP TABLE IF EXISTS vector_documents;
DROP TABLE IF EXISTS vector_fts;
DROP TABLE IF EXISTS edges;
DROP TABLE IF EXISTS nodes;
DROP TABLE IF EXISTS stage1_files;
DROP TABLE IF EXISTS stage1_project_manifest;
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS graph_commits;
DROP TABLE IF EXISTS pipeline_stage_runs;

CREATE TABLE pipeline_stage_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  stage INTEGER NOT NULL CHECK(stage BETWEEN 1 AND 6),
  source_file TEXT NOT NULL,
  generated_at TEXT,
  payload_hash TEXT,
  loaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE graph_commits (
  commit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  schema_version TEXT,
  stage INTEGER NOT NULL CHECK(stage = 6),
  generated_at TEXT,
  commit_metadata_json TEXT NOT NULL,
  source_file TEXT NOT NULL,
  loaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE projects (
  project_id TEXT PRIMARY KEY,
  root_path TEXT,
  project_type TEXT,
  source_doc TEXT,
  confidence TEXT NOT NULL DEFAULT 'HIGH' CHECK(confidence IN ('LOW', 'MEDIUM', 'HIGH')),
  attributes_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE stage1_project_manifest (
  project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
  file_count INTEGER NOT NULL DEFAULT 0,
  extensions_json TEXT NOT NULL,
  generated_at TEXT
);

CREATE TABLE stage1_files (
  file_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  abs_path TEXT NOT NULL,
  rel_path TEXT NOT NULL,
  ext TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  line_count INTEGER,
  sha256 TEXT,
  mtime_utc TEXT
);

CREATE TABLE nodes (
  id TEXT PRIMARY KEY,
  node_type TEXT NOT NULL CHECK(node_type IN (
    'PROJECT', 'REQUIREMENT', 'DECISION', 'DECISION_OPTION',
    'COMPONENT', 'CONSTRAINT', 'EVIDENCE', 'PATTERN', 'SOURCE_DOC', 'ISSUE'
  )),
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  confidence TEXT NOT NULL CHECK(confidence IN ('LOW', 'MEDIUM', 'HIGH')),
  version INTEGER,
  last_updated TEXT,
  parse_uncertain INTEGER NOT NULL DEFAULT 0 CHECK(parse_uncertain IN (0, 1)),
  attributes_json TEXT NOT NULL,
  provenance_stage INTEGER,
  provenance_timestamp TEXT,
  provenance_json TEXT NOT NULL
);

CREATE TABLE node_attribute_kv (
  node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  attr_key TEXT NOT NULL,
  attr_value_json TEXT NOT NULL,
  PRIMARY KEY (node_id, attr_key)
);

CREATE TABLE node_provenance_sources (
  node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  source_order INTEGER NOT NULL,
  source_file TEXT,
  source_line INTEGER,
  source_section TEXT,
  raw_json TEXT NOT NULL,
  PRIMARY KEY (node_id, source_order)
);

CREATE TABLE edges (
  id TEXT PRIMARY KEY,
  edge_type TEXT NOT NULL CHECK(edge_type IN (
    'DECOMPOSES_TO', 'MOTIVATED_BY', 'ALTERNATIVE_TO', 'CHOSE',
    'IMPLEMENTS', 'VERIFIED_BY', 'CONSTRAINED_BY', 'DEPENDS_ON', 'HAS_ISSUE',
    'ANALOGOUS_TO', 'CONTRADICTS', 'INFORMED_BY', 'REUSES_PATTERN', 'SUPERSEDES'
  )),
  source TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  target TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  confidence TEXT NOT NULL CHECK(confidence IN ('LOW', 'MEDIUM', 'HIGH')),
  match_id TEXT,
  match_strategy TEXT,
  attributes_json TEXT NOT NULL,
  provenance_stage INTEGER,
  provenance_timestamp TEXT,
  provenance_json TEXT NOT NULL
);

CREATE TABLE edge_attribute_kv (
  edge_id TEXT NOT NULL REFERENCES edges(id) ON DELETE CASCADE,
  attr_key TEXT NOT NULL,
  attr_value_json TEXT NOT NULL,
  PRIMARY KEY (edge_id, attr_key)
);

CREATE TABLE edge_provenance_sources (
  edge_id TEXT NOT NULL REFERENCES edges(id) ON DELETE CASCADE,
  source_order INTEGER NOT NULL,
  source_file TEXT,
  source_line INTEGER,
  source_section TEXT,
  raw_json TEXT NOT NULL,
  PRIMARY KEY (edge_id, source_order)
);

CREATE TABLE stage4_matches (
  match_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_text TEXT,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  target_name TEXT,
  target_source_file TEXT,
  edge_type TEXT NOT NULL CHECK(edge_type IN ('IMPLEMENTS', 'VERIFIED_BY', 'CONSTRAINED_BY')),
  match_strategy TEXT NOT NULL,
  confidence TEXT NOT NULL CHECK(confidence IN ('LOW', 'MEDIUM', 'HIGH')),
  match_evidence_json TEXT NOT NULL,
  unmatched_aspects_json TEXT NOT NULL,
  primary_edge_id TEXT REFERENCES edges(id) ON DELETE SET NULL
);

CREATE TABLE stage5_findings (
  finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
  finding_type TEXT NOT NULL CHECK(finding_type IN (
    'coverage_gap_requirement',
    'orphan_component',
    'constraint_timing_contradiction',
    'parse_uncertain_violation'
  )),
  project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
  node_id TEXT REFERENCES nodes(id) ON DELETE SET NULL,
  severity TEXT,
  description TEXT,
  details_json TEXT NOT NULL,
  generated_at TEXT
);

CREATE TABLE stage5_metrics (
  metric_key TEXT PRIMARY KEY,
  metric_value_num REAL,
  metric_value_text TEXT,
  generated_at TEXT
);

CREATE TABLE vector_documents (
  vector_id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  confidence TEXT NOT NULL CHECK(confidence IN ('LOW', 'MEDIUM', 'HIGH')),
  text TEXT NOT NULL,
  provenance_stage INTEGER,
  provenance_timestamp TEXT,
  provenance_json TEXT NOT NULL
);

CREATE TABLE vector_provenance_sources (
  vector_id TEXT NOT NULL REFERENCES vector_documents(vector_id) ON DELETE CASCADE,
  source_order INTEGER NOT NULL,
  source_file TEXT,
  source_line INTEGER,
  source_section TEXT,
  raw_json TEXT NOT NULL,
  PRIMARY KEY (vector_id, source_order)
);

CREATE VIRTUAL TABLE vector_fts USING fts5(
  node_id UNINDEXED,
  project_id UNINDEXED,
  text
);

CREATE INDEX idx_stage1_files_project_ext ON stage1_files(project_id, ext);
CREATE INDEX idx_stage1_files_rel_path ON stage1_files(rel_path);
CREATE INDEX idx_nodes_project_type ON nodes(project_id, node_type);
CREATE INDEX idx_nodes_confidence ON nodes(confidence);
CREATE INDEX idx_nodes_last_updated ON nodes(last_updated);
CREATE INDEX idx_node_attr_key ON node_attribute_kv(attr_key);
CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_type ON edges(edge_type);
CREATE INDEX idx_edges_match ON edges(match_id);
CREATE INDEX idx_edge_attr_key ON edge_attribute_kv(attr_key);
CREATE INDEX idx_stage4_source ON stage4_matches(source_id);
CREATE INDEX idx_stage4_target ON stage4_matches(target_id);
CREATE INDEX idx_stage5_type_project ON stage5_findings(finding_type, project_id);
CREATE INDEX idx_vector_docs_node ON vector_documents(node_id);
CREATE INDEX idx_vector_docs_project ON vector_documents(project_id);

PRAGMA foreign_keys = ON;
