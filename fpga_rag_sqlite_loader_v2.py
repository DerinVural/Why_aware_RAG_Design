#!/usr/bin/env python3
"""Load FPGA RAG v2 pipeline artifacts into architecture-aligned SQLite schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "fpga_rag_v2_outputs"

DEFAULT_SCHEMA = BASE_DIR / "fpga_rag_schema_arch_v2.sql"
DEFAULT_DB = OUT_DIR / "fpga_rag_arch_v2_chunked.sqlite"
DEFAULT_STAGE1 = OUT_DIR / "stage1_manifest_v3.json"
DEFAULT_STAGE4 = OUT_DIR / "stage4_matching_details_v3.json"
DEFAULT_STAGE5 = OUT_DIR / "stage5_gap_analysis_v3.json"
DEFAULT_STAGE6 = OUT_DIR / "stage6_graph_vector_commit_v4_chunked.json"

CONF = {"LOW", "MEDIUM", "HIGH"}


def normalize_conf(value: Any) -> str:
    v = str(value or "").strip().upper()
    return v if v in CONF else "MEDIUM"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_project(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    root_path: Optional[str] = None,
    project_type: Optional[str] = None,
    source_doc: Optional[str] = None,
    confidence: str = "HIGH",
    attributes: Optional[Dict[str, Any]] = None,
) -> None:
    attrs = attributes or {}
    conn.execute(
        """
        INSERT INTO projects(project_id, root_path, project_type, source_doc, confidence, attributes_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET
          root_path = COALESCE(excluded.root_path, projects.root_path),
          project_type = COALESCE(excluded.project_type, projects.project_type),
          source_doc = COALESCE(excluded.source_doc, projects.source_doc),
          confidence = COALESCE(excluded.confidence, projects.confidence),
          attributes_json = CASE
            WHEN projects.attributes_json = '{}' THEN excluded.attributes_json
            ELSE projects.attributes_json
          END
        """,
        (
            project_id,
            root_path,
            project_type,
            source_doc,
            normalize_conf(confidence),
            json_dump(attrs),
        ),
    )


def record_stage_run(conn: sqlite3.Connection, stage: int, source_file: Path, generated_at: Optional[str]) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_stage_runs(stage, source_file, generated_at, payload_hash)
        VALUES (?, ?, ?, ?)
        """,
        (stage, str(source_file), generated_at, file_sha256(source_file)),
    )


def parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def infer_project_id(node_id: Optional[str]) -> Optional[str]:
    if not node_id:
        return None
    if node_id.startswith("PROJECT-A:"):
        return "PROJECT-A"
    if node_id.startswith("PROJECT-B:"):
        return "PROJECT-B"
    if "DMA-REQ-" in node_id or "DMA-DEC-" in node_id:
        return "PROJECT-A"
    if "AXI-REQ-" in node_id or "AXI-DEC-" in node_id:
        return "PROJECT-B"
    return None


def node_project(conn: sqlite3.Connection, node_id: Optional[str]) -> Optional[str]:
    if not node_id:
        return None
    row = conn.execute("SELECT project_id FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row:
        return row[0]
    return infer_project_id(node_id)


def load_stage1(conn: sqlite3.Connection, stage1_path: Path) -> None:
    payload = load_json(stage1_path)
    record_stage_run(conn, 1, stage1_path, payload.get("generated_at"))
    projects = payload.get("projects", {})

    for project_id, data in projects.items():
        ensure_project(
            conn,
            project_id,
            root_path=data.get("root"),
            confidence="HIGH",
            attributes={"extensions": data.get("extensions", {}), "stage": 1},
        )
        conn.execute(
            """
            INSERT INTO stage1_project_manifest(project_id, file_count, extensions_json, generated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                project_id,
                int(data.get("file_count", 0)),
                json_dump(data.get("extensions", {})),
                payload.get("generated_at"),
            ),
        )

        files = data.get("files", [])
        conn.executemany(
            """
            INSERT INTO stage1_files(file_id, project_id, abs_path, rel_path, ext, size_bytes, line_count, sha256, mtime_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f["file_id"],
                    project_id,
                    f.get("abs_path", ""),
                    f.get("rel_path", ""),
                    f.get("ext", ""),
                    int(f.get("size_bytes", 0)),
                    parse_int(f.get("line_count")),
                    f.get("sha256"),
                    f.get("mtime_utc"),
                )
                for f in files
            ],
        )


def load_stage6(conn: sqlite3.Connection, stage6_path: Path) -> Dict[str, List[str]]:
    payload = load_json(stage6_path)
    record_stage_run(conn, 6, stage6_path, payload.get("generated_at"))
    conn.execute(
        """
        INSERT INTO graph_commits(schema_version, stage, generated_at, commit_metadata_json, source_file)
        VALUES (?, 6, ?, ?, ?)
        """,
        (
            payload.get("schema_version"),
            payload.get("generated_at"),
            json_dump(payload.get("commit_metadata", {})),
            str(stage6_path),
        ),
    )

    graph = payload.get("graph", {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    vectors = payload.get("vector_documents", [])

    # Ensure project registry before FK inserts.
    seen_projects = set()
    for item in nodes:
        pid = item.get("project_id")
        if pid and pid not in seen_projects:
            ensure_project(conn, pid, confidence="HIGH")
            seen_projects.add(pid)
    for item in vectors:
        pid = item.get("project_id")
        if pid and pid not in seen_projects:
            ensure_project(conn, pid, confidence="HIGH")
            seen_projects.add(pid)

    node_rows: List[tuple] = []
    node_attr_rows: List[tuple] = []
    node_src_rows: List[tuple] = []
    for n in nodes:
        attrs = n.get("attributes", {}) or {}
        prov = n.get("provenance", {}) or {}
        node_rows.append(
            (
                n["id"],
                n["node_type"],
                n["project_id"],
                n.get("name", ""),
                normalize_conf(n.get("confidence")),
                parse_int(attrs.get("version")),
                attrs.get("last_updated"),
                1 if attrs.get("parse_uncertain") else 0,
                json_dump(attrs),
                parse_int(prov.get("stage")),
                prov.get("timestamp"),
                json_dump(prov),
            )
        )
        for k, v in attrs.items():
            node_attr_rows.append((n["id"], k, json_dump(v)))
        for i, src in enumerate(prov.get("sources", []) or []):
            node_src_rows.append(
                (
                    n["id"],
                    i,
                    src.get("file"),
                    parse_int(src.get("line")),
                    src.get("section"),
                    json_dump(src),
                )
            )

    conn.executemany(
        """
        INSERT INTO nodes(
          id, node_type, project_id, name, confidence, version, last_updated, parse_uncertain,
          attributes_json, provenance_stage, provenance_timestamp, provenance_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        node_rows,
    )
    if node_attr_rows:
        conn.executemany(
            "INSERT INTO node_attribute_kv(node_id, attr_key, attr_value_json) VALUES (?, ?, ?)",
            node_attr_rows,
        )
    if node_src_rows:
        conn.executemany(
            """
            INSERT INTO node_provenance_sources(node_id, source_order, source_file, source_line, source_section, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            node_src_rows,
        )

    edge_rows: List[tuple] = []
    edge_attr_rows: List[tuple] = []
    edge_src_rows: List[tuple] = []
    edge_match_map: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        attrs = e.get("attributes", {}) or {}
        prov = e.get("provenance", {}) or {}
        match_id = attrs.get("match_id")
        match_strategy = attrs.get("match_strategy")
        edge_rows.append(
            (
                e["id"],
                e["edge_type"],
                e["source"],
                e["target"],
                normalize_conf(e.get("confidence")),
                match_id,
                match_strategy,
                json_dump(attrs),
                parse_int(prov.get("stage")),
                prov.get("timestamp"),
                json_dump(prov),
            )
        )
        if match_id:
            edge_match_map[str(match_id)].append(e["id"])
        for k, v in attrs.items():
            edge_attr_rows.append((e["id"], k, json_dump(v)))
        for i, src in enumerate(prov.get("sources", []) or []):
            edge_src_rows.append(
                (
                    e["id"],
                    i,
                    src.get("file"),
                    parse_int(src.get("line")),
                    src.get("section"),
                    json_dump(src),
                )
            )

    conn.executemany(
        """
        INSERT INTO edges(
          id, edge_type, source, target, confidence, match_id, match_strategy,
          attributes_json, provenance_stage, provenance_timestamp, provenance_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        edge_rows,
    )
    if edge_attr_rows:
        conn.executemany(
            "INSERT INTO edge_attribute_kv(edge_id, attr_key, attr_value_json) VALUES (?, ?, ?)",
            edge_attr_rows,
        )
    if edge_src_rows:
        conn.executemany(
            """
            INSERT INTO edge_provenance_sources(edge_id, source_order, source_file, source_line, source_section, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            edge_src_rows,
        )

    vector_rows: List[tuple] = []
    vector_fts_rows: List[tuple] = []
    vector_src_rows: List[tuple] = []
    for v in vectors:
        prov = v.get("provenance", {}) or {}
        vector_rows.append(
            (
                v["vector_id"],
                v["node_id"],
                v["project_id"],
                normalize_conf(v.get("confidence")),
                v.get("text", ""),
                parse_int(prov.get("stage")),
                prov.get("timestamp"),
                json_dump(prov),
            )
        )
        vector_fts_rows.append((v["node_id"], v["project_id"], v.get("text", "")))
        for i, src in enumerate(prov.get("sources", []) or []):
            vector_src_rows.append(
                (
                    v["vector_id"],
                    i,
                    src.get("file"),
                    parse_int(src.get("line")),
                    src.get("section"),
                    json_dump(src),
                )
            )

    conn.executemany(
        """
        INSERT INTO vector_documents(
          vector_id, node_id, project_id, confidence, text, provenance_stage, provenance_timestamp, provenance_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        vector_rows,
    )
    conn.executemany(
        "INSERT INTO vector_fts(node_id, project_id, text) VALUES (?, ?, ?)",
        vector_fts_rows,
    )
    if vector_src_rows:
        conn.executemany(
            """
            INSERT INTO vector_provenance_sources(vector_id, source_order, source_file, source_line, source_section, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            vector_src_rows,
        )

    return edge_match_map


def load_stage4(conn: sqlite3.Connection, stage4_path: Path, edge_match_map: Dict[str, List[str]]) -> None:
    payload = load_json(stage4_path)
    # stage4 details file is a direct list
    record_stage_run(conn, 4, stage4_path, None)
    rows: List[tuple] = []
    for m in payload:
        match_id = str(m.get("match_id"))
        source = m.get("source", {}) or {}
        target = m.get("target", {}) or {}
        rows.append(
            (
                match_id,
                source.get("type", ""),
                source.get("id", ""),
                source.get("text"),
                target.get("type", ""),
                target.get("id", ""),
                target.get("name"),
                target.get("source_file"),
                m.get("edge_type", ""),
                m.get("match_strategy", ""),
                normalize_conf(m.get("confidence")),
                json_dump(m.get("match_evidence", [])),
                json_dump(m.get("unmatched_aspects", [])),
                (edge_match_map.get(match_id) or [None])[0],
            )
        )
    conn.executemany(
        """
        INSERT INTO stage4_matches(
          match_id, source_type, source_id, source_text, target_type, target_id, target_name,
          target_source_file, edge_type, match_strategy, confidence, match_evidence_json,
          unmatched_aspects_json, primary_edge_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def add_stage5_finding(
    conn: sqlite3.Connection,
    *,
    finding_type: str,
    project_id: Optional[str],
    node_id: Optional[str],
    severity: Optional[str],
    description: Optional[str],
    details: Any,
    generated_at: Optional[str],
) -> None:
    conn.execute(
        """
        INSERT INTO stage5_findings(
          finding_type, project_id, node_id, severity, description, details_json, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            finding_type,
            project_id,
            node_id,
            severity,
            description,
            json_dump(details),
            generated_at,
        ),
    )


def load_stage5(conn: sqlite3.Connection, stage5_path: Path) -> None:
    payload = load_json(stage5_path)
    generated_at = payload.get("generated_at")
    record_stage_run(conn, 5, stage5_path, generated_at)

    for req_id in payload.get("coverage_gap_requirements", []) or []:
        add_stage5_finding(
            conn,
            finding_type="coverage_gap_requirement",
            project_id=node_project(conn, req_id),
            node_id=req_id,
            severity="medium",
            description="Requirement has no matched implementation.",
            details={"requirement_id": req_id},
            generated_at=generated_at,
        )

    for comp_id in payload.get("orphan_components", []) or []:
        add_stage5_finding(
            conn,
            finding_type="orphan_component",
            project_id=node_project(conn, comp_id),
            node_id=comp_id,
            severity="medium",
            description="Component is not linked to any requirement.",
            details={"component_id": comp_id},
            generated_at=generated_at,
        )

    for obj in payload.get("constraint_timing_contradictions", []) or []:
        issue_id = obj.get("issue_id")
        add_stage5_finding(
            conn,
            finding_type="constraint_timing_contradiction",
            project_id=node_project(conn, issue_id),
            node_id=issue_id,
            severity=obj.get("severity"),
            description=obj.get("description"),
            details=obj,
            generated_at=generated_at,
        )

    for obj in payload.get("parse_uncertain_violations", []) or []:
        if isinstance(obj, dict):
            node_id = obj.get("node_id")
            details = obj
            desc = obj.get("description") or "PARSE_UNCERTAIN violation."
            sev = obj.get("severity") or "medium"
        else:
            node_id = str(obj)
            details = {"node_id": node_id}
            desc = "PARSE_UNCERTAIN violation."
            sev = "medium"
        add_stage5_finding(
            conn,
            finding_type="parse_uncertain_violation",
            project_id=node_project(conn, node_id),
            node_id=node_id,
            severity=sev,
            description=desc,
            details=details,
            generated_at=generated_at,
        )

    metric_keys = [
        "cross_project_edge_count",
        "issue_link_edge_count",
        "stage5_derived_node_count",
        "stage5_derived_edge_count",
    ]
    for key in metric_keys:
        val = payload.get(key)
        conn.execute(
            """
            INSERT INTO stage5_metrics(metric_key, metric_value_num, metric_value_text, generated_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, float(val) if isinstance(val, (int, float)) else None, None if isinstance(val, (int, float)) else str(val), generated_at),
        )

    special = payload.get("special_analyses")
    if special is not None:
        conn.execute(
            """
            INSERT INTO stage5_metrics(metric_key, metric_value_num, metric_value_text, generated_at)
            VALUES (?, NULL, ?, ?)
            """,
            ("special_analyses", json_dump(special), generated_at),
        )


def init_db(conn: sqlite3.Connection, schema_path: Path) -> None:
    script = schema_path.read_text(encoding="utf-8")
    conn.executescript(script)


def count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Load architecture-v2 aligned FPGA RAG SQLite DB")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--stage1", default=str(DEFAULT_STAGE1))
    parser.add_argument("--stage4", default=str(DEFAULT_STAGE4))
    parser.add_argument("--stage5", default=str(DEFAULT_STAGE5))
    parser.add_argument("--stage6", default=str(DEFAULT_STAGE6))
    args = parser.parse_args()

    schema_path = Path(args.schema)
    db_path = Path(args.db)
    stage1_path = Path(args.stage1)
    stage4_path = Path(args.stage4)
    stage5_path = Path(args.stage5)
    stage6_path = Path(args.stage6)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn, schema_path)
        load_stage1(conn, stage1_path)
        edge_match_map = load_stage6(conn, stage6_path)
        load_stage4(conn, stage4_path, edge_match_map)
        load_stage5(conn, stage5_path)
        conn.commit()

        print(f"DB ready: {db_path}")
        print(
            "counts:",
            {
                "projects": count(conn, "projects"),
                "stage1_files": count(conn, "stage1_files"),
                "nodes": count(conn, "nodes"),
                "edges": count(conn, "edges"),
                "stage4_matches": count(conn, "stage4_matches"),
                "stage5_findings": count(conn, "stage5_findings"),
                "vector_documents": count(conn, "vector_documents"),
            },
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
