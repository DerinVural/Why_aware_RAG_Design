#!/usr/bin/env python3
"""FPGA RAG v4 query utility with JSON/SQLite dual backend."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "fpga_rag_v2_outputs"
DEFAULT_GRAPH = OUT_DIR / "stage6_graph_vector_commit_v4_chunked.json"
DEFAULT_DB = OUT_DIR / "fpga_rag_arch_v2_chunked.sqlite"

CONF_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
RANK_CONF = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}


def tokenize(text: str) -> Set[str]:
    return set(re.findall(r"[a-zA-Z0-9_çğıöşüÇĞİÖŞÜ]{2,}", text.lower()))


EXISTENCE_STOPWORDS = {
    "bu",
    "projede",
    "proje",
    "var",
    "mi",
    "mı",
    "mu",
    "mü",
    "ve",
    "ile",
    "için",
    "the",
    "is",
    "are",
    "in",
    "on",
}


def existence_focus_tokens(query: str) -> Set[str]:
    return {t for t in tokenize(query) if len(t) >= 3 and t not in EXISTENCE_STOPWORDS}


def normalize_conf(conf: Any) -> str:
    value = str(conf or "").strip().upper()
    if value in {"LOW", "MEDIUM", "HIGH"}:
        return value
    return "MEDIUM"


def min_confidence(values: Iterable[str]) -> str:
    ranks = [CONF_RANK.get(normalize_conf(v), 2) for v in values]
    if not ranks:
        return "MEDIUM"
    return RANK_CONF[min(ranks)]


def route_query(query: str) -> str:
    q_tokens = tokenize(query)
    q_text = query.lower()
    why_tokens = {"neden", "niye", "why", "gerekçe", "motivasyon", "sebep", "karar"}
    trace_tokens = {"trace", "iz", "akış", "path", "traverse", "zincir", "hiyerarşi", "alt", "kırılım"}
    cross_tokens = {"cross", "çapraz", "analogous", "benzer", "fark", "karşılaştır", "crossref"}
    if q_tokens & why_tokens:
        return "WHY"
    if q_tokens & trace_tokens:
        return "TRACE"
    if q_tokens & cross_tokens or ("iki proje" in q_text):
        return "CROSSREF"
    return "WHAT"


def detect_scope(query: str, qtype: str) -> Optional[str]:
    q = query.lower()
    has_dma = any(
        k in q
        for k in [
            "project-a",
            "project a",
            "proje-a",
            "proje a",
            "dma",
            "nexys-a7",
            "nexys a7",
        ]
    )
    has_axi = any(
        k in q
        for k in [
            "project-b",
            "project b",
            "proje-b",
            "proje b",
            "axi_example",
            "axi example",
        ]
    )
    if re.search(r"\bproje\s*[- ]?a\b", q, re.IGNORECASE):
        has_dma = True
    if re.search(r"\bproje\s*[- ]?b\b", q, re.IGNORECASE):
        has_axi = True
    if re.search(r"\bDMA-REQ-L\d-\d{3}\b", query, re.IGNORECASE) or re.search(r"\bDMA-DEC-\d{3}\b", query, re.IGNORECASE):
        has_dma = True
    if re.search(r"\bAXI-REQ-L\d-\d{3}\b", query, re.IGNORECASE) or re.search(r"\bAXI-DEC-\d{3}\b", query, re.IGNORECASE):
        has_axi = True
    if qtype == "CROSSREF":
        if has_dma and not has_axi:
            return "PROJECT-A"
        if has_axi and not has_dma:
            return "PROJECT-B"
        return None
    if has_dma and not has_axi:
        return "PROJECT-A"
    if has_axi and not has_dma:
        return "PROJECT-B"
    return None


class SQLiteQueryEngine:
    def __init__(self, db_path: Path) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.vector_doc_table = "vector_documents"
        self.node_by_id: Dict[str, Dict[str, Any]] = {}
        self.node_tokens: Dict[str, Set[str]] = {}
        self.node_text_excerpt: Dict[str, str] = {}
        self.out_adj: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.in_adj: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._load_cache()

    def close(self) -> None:
        self.conn.close()

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table_name,)
        ).fetchone()
        return row is not None

    def _load_cache(self) -> None:
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT id, node_type, project_id, name, confidence, attributes_json FROM nodes"
        ).fetchall()
        for r in rows:
            try:
                attrs = json.loads(r["attributes_json"]) if r["attributes_json"] else {}
            except Exception:
                attrs = {}
            item = {
                "id": r["id"],
                "node_type": r["node_type"],
                "project_id": r["project_id"],
                "name": r["name"],
                "confidence": r["confidence"],
                "attributes_json": r["attributes_json"],
                "attributes": attrs,
            }
            self.node_by_id[r["id"]] = item
            self.node_tokens[r["id"]] = tokenize(f"{r['id']} {r['name']} {json.dumps(attrs, ensure_ascii=False)}")
        if self._table_exists("vector_documents"):
            self.vector_doc_table = "vector_documents"
        elif self._table_exists("vector_docs"):
            self.vector_doc_table = "vector_docs"
        else:
            self.vector_doc_table = ""
        vrows: List[sqlite3.Row] = []
        if self.vector_doc_table:
            vrows = cur.execute(f"SELECT node_id, text FROM {self.vector_doc_table}").fetchall()
        for r in vrows:
            # Keep the first excerpt for a stable short citation view when node has multi-chunk vectors.
            if r["node_id"] not in self.node_text_excerpt:
                self.node_text_excerpt[r["node_id"]] = (r["text"] or "")[:220]
        erows = cur.execute(
            "SELECT id, edge_type, source, target, confidence FROM edges"
        ).fetchall()
        for e in erows:
            edge = {
                "id": e["id"],
                "edge_type": e["edge_type"],
                "source": e["source"],
                "target": e["target"],
                "confidence": e["confidence"],
            }
            self.out_adj[e["source"]].append(edge)
            self.in_adj[e["target"]].append(edge)

    def _extract_ids(self, query: str) -> List[str]:
        ids: List[str] = []
        reqs = re.findall(r"(DMA-REQ-L[0-2]-\d{3}|AXI-REQ-L[0-2]-\d{3})", query, re.IGNORECASE)
        decs = re.findall(r"(DMA-DEC-\d{3}|AXI-DEC-\d{3})", query, re.IGNORECASE)
        for x in reqs + decs:
            ids.append(f"STAGE3:{x.upper()}")
        return ids

    def _filter_edge_scope(self, edge: Dict[str, Any], scope: Optional[str], strict: bool = False) -> bool:
        if not scope:
            return True
        s = self.node_by_id.get(edge["source"], {})
        t = self.node_by_id.get(edge["target"], {})
        if strict:
            return s.get("project_id") == scope and t.get("project_id") == scope
        return s.get("project_id") == scope or t.get("project_id") == scope

    def _semantic_rank(self, query: str, scope: Optional[str], limit: int = 24) -> Dict[str, float]:
        tokens = [t for t in tokenize(query) if len(t) >= 2]
        if not tokens:
            return {}
        fts_expr = " OR ".join([f"{t}*" for t in list(tokens)[:12]])
        sql = (
            "SELECT vf.node_id, bm25(vector_fts) AS r "
            "FROM vector_fts vf "
            "JOIN nodes n ON n.id=vf.node_id "
            "WHERE vector_fts MATCH ? "
        )
        params: List[Any] = [fts_expr]
        if scope:
            sql += "AND n.project_id=? "
            params.append(scope)
        sql += "ORDER BY r LIMIT ?"
        params.append(limit)

        out: Dict[str, float] = {}
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for idx, row in enumerate(rows):
            # bm25 lower is better; convert to positive descending score.
            score = max(0.01, 2.0 - (idx * 0.07))
            prev = out.get(row["node_id"], 0.0)
            # Multi-chunk vectors can produce repeated node_id rows; keep best score per node.
            out[row["node_id"]] = score if score > prev else prev
        return out

    def _is_address_question(self, question: str) -> bool:
        q = question.lower()
        keys = {
            "adres",
            "address",
            "awaddr",
            "araddr",
            "axi4-lite",
            "axi4 lite",
            "s_axi",
            "base address",
        }
        return any(k in q for k in keys)

    def _is_led_pin_question(self, question: str) -> bool:
        q = question.lower()
        has_led = any(k in q for k in {"led", "leds", "led_8bits", "leds_8bits"})
        has_pin = any(k in q for k in {"pin", "package_pin", "atan", "atandı", "atama", "assignment"})
        return has_led and has_pin

    def _led_pin_assignments(self, scope: Optional[str]) -> Tuple[List[str], Set[str]]:
        assignments: Dict[int, str] = {}
        node_ids: Set[str] = set()
        for nid, meta in self.node_by_id.items():
            if scope and meta.get("project_id") != scope:
                continue
            if meta.get("node_type") != "CONSTRAINT":
                continue
            attrs = meta.get("attributes", {}) or {}
            ctype = str(attrs.get("constraint_type", "")).lower()
            if ctype not in {"pin", "pin_assignment"}:
                continue
            spec = str(attrs.get("spec", ""))
            if "PACKAGE_PIN" not in spec or "led" not in spec.lower():
                continue
            pin_m = re.search(r"PACKAGE_PIN\s+([A-Za-z0-9_]+)", spec)
            port_m = re.search(r"\[get_ports\s+\{?([A-Za-z0-9_]+)\[(\d+)\]\}?\]", spec)
            if not pin_m or not port_m:
                continue
            port_name = port_m.group(1).lower()
            if "led" not in port_name:
                continue
            idx = int(port_m.group(2))
            pin = pin_m.group(1)
            assignments[idx] = pin
            node_ids.add(nid)

        ordered = [f"LED[{i}]={assignments[i]}" for i in sorted(assignments.keys())]
        return ordered, node_ids

    def _axi_gpio_config_from_sources(self, scope: Optional[str]) -> Dict[str, Any]:
        candidate_files: Set[str] = set()
        for meta in self.node_by_id.values():
            if scope and meta.get("project_id") != scope:
                continue
            attrs = meta.get("attributes", {}) or {}
            src = attrs.get("source_file")
            name = str(meta.get("name", "")).lower()
            if isinstance(src, str) and src and ("axi" in src.lower() or "gpio" in src.lower() or "tcl" in src.lower()):
                candidate_files.add(src)
            if "axi_gpio" in name and isinstance(src, str) and src:
                candidate_files.add(src)

        best: Dict[str, Any] = {}
        for f in sorted(candidate_files):
            p = Path(f)
            if not p.exists() or not p.is_file():
                continue
            if p.suffix.lower() != ".tcl":
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            c_gpio = re.search(r"CONFIG\.C_GPIO_WIDTH\s*\{?(\d+)\}?", text)
            c_gpio2 = re.search(r"CONFIG\.C_GPIO2_WIDTH\s*\{?(\d+)\}?", text)
            c_dual = re.search(r"CONFIG\.C_IS_DUAL\s*\{?([01])\}?", text)
            if not (c_gpio or c_gpio2 or c_dual):
                continue

            cfg = {
                "file": f,
                "gpio_width": int(c_gpio.group(1)) if c_gpio else None,
                "gpio2_width": int(c_gpio2.group(1)) if c_gpio2 else None,
                "is_dual": int(c_dual.group(1)) if c_dual else None,
            }
            score = 0
            if cfg["is_dual"] is not None:
                score += 3
            if cfg["gpio_width"] is not None:
                score += 2
            if cfg["gpio2_width"] is not None:
                score += 1
            if "create_axi_with_xdc" in f:
                score += 2
            cfg["score"] = score
            if not best or score > best.get("score", -1):
                best = cfg
        return best

    def _address_focus_nodes(self, scope: Optional[str]) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
        out: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {
            "signals": [],
            "segments": [],
            "maps": [],
        }
        for nid, meta in self.node_by_id.items():
            if scope and meta.get("project_id") != scope:
                continue
            attrs = meta.get("attributes", {}) or {}
            if meta.get("node_type") == "EVIDENCE" and attrs.get("evidence_type") == "axi4lite_signal_binding":
                out["signals"].append((nid, meta))
            if attrs.get("constraint_type") == "axi_address_assignment" or attrs.get("evidence_type") == "tcl_address_assignment":
                out["segments"].append((nid, meta))
            if attrs.get("constraint_type") == "axi_address_map" or attrs.get("evidence_type") == "address_map_table":
                out["maps"].append((nid, meta))
        return out

    def _rank_nodes(self, query: str, scope: Optional[str], limit: int = 12) -> List[Tuple[float, Dict[str, Any]]]:
        qtok = tokenize(query)
        sem = self._semantic_rank(query, scope=scope, limit=36)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for nid, meta in self.node_by_id.items():
            if scope and meta.get("project_id") != scope:
                continue
            lex = float(len(qtok & self.node_tokens.get(nid, set())))
            sems = float(sem.get(nid, 0.0))
            combined = lex + sems
            if lex <= 0 and sems < 0.05:
                continue
            scored.append((combined, meta))
        scored.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
        return scored[:limit]

    def _collect_one_hop(
        self,
        anchor_ids: Set[str],
        edge_types: Optional[Set[str]],
        scope: Optional[str],
        strict_scope: bool = False,
        max_edges: int = 64,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for nid in anchor_ids:
            for e in self.out_adj.get(nid, []) + self.in_adj.get(nid, []):
                if edge_types and e["edge_type"] not in edge_types:
                    continue
                if not self._filter_edge_scope(e, scope, strict=strict_scope):
                    continue
                if e["id"] in seen:
                    continue
                seen.add(e["id"])
                out.append(e)
                if len(out) >= max_edges:
                    return out
        return out

    def _trace_req_tree(
        self, anchor_reqs: Set[str], scope: Optional[str], max_depth: int = 3
    ) -> Tuple[Set[str], List[Dict[str, Any]], List[str]]:
        req_nodes: Set[str] = set(anchor_reqs)
        edges: List[Dict[str, Any]] = []
        path: List[str] = []
        seen: Set[str] = set()
        q: deque[Tuple[str, int]] = deque((x, 0) for x in sorted(anchor_reqs))
        visited: Set[str] = set(anchor_reqs)

        while q:
            cur, depth = q.popleft()
            if depth >= max_depth:
                continue
            for e in self.out_adj.get(cur, []) + self.in_adj.get(cur, []):
                if e["edge_type"] != "DECOMPOSES_TO":
                    continue
                if not self._filter_edge_scope(e, scope):
                    continue
                if e["id"] not in seen:
                    seen.add(e["id"])
                    edges.append(e)
                    path.append(f"{e['source']} -DECOMPOSES_TO-> {e['target']}")
                nxt = e["target"] if e["source"] == cur else e["source"]
                nmeta = self.node_by_id.get(nxt, {})
                if nmeta.get("node_type") != "REQUIREMENT":
                    continue
                req_nodes.add(nxt)
                if nxt not in visited:
                    visited.add(nxt)
                    q.append((nxt, depth + 1))

        for rid in sorted(req_nodes):
            for e in self.out_adj.get(rid, []) + self.in_adj.get(rid, []):
                if e["edge_type"] not in {"IMPLEMENTS", "VERIFIED_BY", "CONSTRAINED_BY", "CONTRADICTS"}:
                    continue
                if not self._filter_edge_scope(e, scope):
                    continue
                if e["id"] in seen:
                    continue
                seen.add(e["id"])
                edges.append(e)
        return req_nodes, edges[:64], path[:64]

    def _why_traversal(
        self, anchor_decisions: Set[str], scope: Optional[str]
    ) -> Tuple[Set[str], List[Dict[str, Any]], List[str]]:
        node_ids: Set[str] = set(anchor_decisions)
        edges: List[Dict[str, Any]] = []
        path: List[str] = []
        seen: Set[str] = set()
        frontier: Set[str] = set(anchor_decisions)
        types = {"MOTIVATED_BY", "CHOSE", "ALTERNATIVE_TO", "CONTRADICTS"}
        for _ in range(2):
            nxt_frontier: Set[str] = set()
            for nid in sorted(frontier):
                for e in self.out_adj.get(nid, []) + self.in_adj.get(nid, []):
                    if e["edge_type"] not in types:
                        continue
                    if not self._filter_edge_scope(e, scope):
                        continue
                    if e["id"] in seen:
                        continue
                    seen.add(e["id"])
                    edges.append(e)
                    path.append(f"{e['source']} -{e['edge_type']}-> {e['target']}")
                    node_ids.add(e["source"])
                    node_ids.add(e["target"])
                    nxt_frontier.add(e["source"])
                    nxt_frontier.add(e["target"])
            frontier = nxt_frontier
        return node_ids, edges[:64], path[:64]

    def _format_citations(self, node_ids: Set[str], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
        nout: List[Dict[str, Any]] = []
        for nid in sorted(node_ids):
            meta = self.node_by_id.get(nid)
            if not meta:
                continue
            nout.append(
                {
                    "node_id": nid,
                    "node_type": meta.get("node_type"),
                    "confidence": normalize_conf(meta.get("confidence")),
                    "text": self.node_text_excerpt.get(nid, meta.get("name", ""))[:220],
                }
            )
        eout: List[Dict[str, Any]] = []
        for e in edges:
            eout.append(
                {
                    "edge_id": e["id"],
                    "edge_type": e["edge_type"],
                    "source": e["source"],
                    "target": e["target"],
                    "confidence": normalize_conf(e.get("confidence")),
                }
            )
        return {"nodes": nout[:24], "edges": eout[:48]}

    def query(self, question: str) -> Dict[str, Any]:
        qtype = route_query(question)
        scope = detect_scope(question, qtype)
        ranked = self._rank_nodes(question, scope=scope, limit=12)
        top_score = ranked[0][0] if ranked else 0.0
        explicit_ids = self._extract_ids(question)

        anchor_ids: Set[str] = set(explicit_ids)
        anchor_ids.update([n["id"] for _, n in ranked[:6]])
        if scope:
            anchor_ids = {nid for nid in anchor_ids if self.node_by_id.get(nid, {}).get("project_id") == scope}

        node_ids: Set[str] = set(anchor_ids)
        used_edges: List[Dict[str, Any]] = []
        traversal_path: List[str] = []
        vector_store = "vector_tfidf_cosine_sqlite_fts"
        if self.vector_doc_table:
            vector_store = f"{vector_store}:{self.vector_doc_table}"
        stores = ["graph", vector_store]

        if qtype == "TRACE":
            req_anchors = {nid for nid in anchor_ids if self.node_by_id.get(nid, {}).get("node_type") == "REQUIREMENT"}
            if not req_anchors:
                req_anchors = {n["id"] for _, n in ranked if n.get("node_type") == "REQUIREMENT"}
            req_nodes, trace_edges, path = self._trace_req_tree(req_anchors, scope=scope, max_depth=3)
            node_ids.update(req_nodes)
            used_edges = trace_edges
            traversal_path = path
        elif qtype == "WHY":
            dec_anchors = {nid for nid in anchor_ids if self.node_by_id.get(nid, {}).get("node_type") == "DECISION"}
            if not dec_anchors:
                dec_anchors = {n["id"] for _, n in ranked if n.get("node_type") == "DECISION"}
            why_nodes, why_edges, path = self._why_traversal(dec_anchors, scope=scope)
            node_ids.update(why_nodes)
            used_edges = why_edges
            traversal_path = path
        elif qtype == "CROSSREF":
            used_edges = self._collect_one_hop(
                anchor_ids,
                {"ANALOGOUS_TO", "REUSES_PATTERN", "CONTRADICTS", "INFORMED_BY"},
                scope=None,
                strict_scope=False,
                max_edges=64,
            )
            if len(used_edges) < 3:
                seen = {e["id"] for e in used_edges}
                for src, lst in self.out_adj.items():
                    for e in lst:
                        if e["id"] in seen:
                            continue
                        if e["edge_type"] not in {"ANALOGOUS_TO", "REUSES_PATTERN", "CONTRADICTS", "INFORMED_BY"}:
                            continue
                        used_edges.append(e)
                        seen.add(e["id"])
                        if len(used_edges) >= 64:
                            break
                    if len(used_edges) >= 64:
                        break
        else:
            used_edges = self._collect_one_hop(
                anchor_ids,
                None,
                scope=scope,
                strict_scope=bool(scope),
                max_edges=48,
            )

        for e in used_edges:
            node_ids.add(e["source"])
            node_ids.add(e["target"])

        if qtype == "WHAT" and scope:
            node_ids = {nid for nid in node_ids if self.node_by_id.get(nid, {}).get("project_id") == scope}
            used_edges = [
                e
                for e in used_edges
                if self.node_by_id.get(e["source"], {}).get("project_id") == scope
                and self.node_by_id.get(e["target"], {}).get("project_id") == scope
            ]

        existence_query = ("var mı" in question.lower()) or ("var mi" in question.lower())
        focus_tokens = existence_focus_tokens(question) if existence_query else set()
        technical_types = {"COMPONENT", "CONSTRAINT", "EVIDENCE", "PATTERN", "ISSUE"}
        node_types = {self.node_by_id.get(nid, {}).get("node_type", "") for nid in node_ids}
        has_technical = bool(node_types & technical_types)
        lexical_focus_match = False
        if focus_tokens:
            for nid in anchor_ids:
                ntype = self.node_by_id.get(nid, {}).get("node_type")
                if ntype not in technical_types:
                    continue
                ntoks = self.node_tokens.get(nid, set())
                if ntoks & focus_tokens:
                    lexical_focus_match = True
                    break

        gate_pass = bool(node_ids or used_edges)
        if qtype in {"WHY", "TRACE", "CROSSREF"}:
            gate_pass = gate_pass and len(used_edges) > 0
        if existence_query and not has_technical:
            gate_pass = False
        if existence_query and focus_tokens and not lexical_focus_match and not explicit_ids:
            gate_pass = False
        if top_score < 0.2 and not explicit_ids:
            gate_pass = False

        warnings: List[str] = []
        contradictions = [e for e in used_edges if e["edge_type"] == "CONTRADICTS"]
        if contradictions:
            warnings.append(f"CONTRADICTION_PRESENT:{len(contradictions)}")

        confidences: List[str] = []
        for nid in node_ids:
            meta = self.node_by_id.get(nid)
            if meta:
                confidences.append(normalize_conf(meta.get("confidence")))
        confidences += [normalize_conf(e.get("confidence")) for e in used_edges]
        chain_conf = min_confidence(confidences)
        if chain_conf != "HIGH":
            warnings.append(f"LOW_CHAIN_CONFIDENCE:{chain_conf}")

        citations = self._format_citations(node_ids, used_edges)
        if not gate_pass:
            answer = "Bu bilgi veritabanında bulunamadı."
            citations = {"nodes": [], "edges": []}
            warnings.append("NO_EVIDENCE_GATE_TRIGGERED")
            chain_conf = "MEDIUM"
        elif self._is_led_pin_question(question):
            ordered, pin_node_ids = self._led_pin_assignments(scope)
            node_ids.update(pin_node_ids)
            cfg = self._axi_gpio_config_from_sources(scope)
            extra_edges = self._collect_one_hop(
                pin_node_ids,
                {"CONSTRAINED_BY", "VERIFIED_BY"},
                scope=scope,
                strict_scope=bool(scope),
                max_edges=32,
            )
            seen_edges = {e["id"] for e in used_edges}
            for e in extra_edges:
                if e["id"] not in seen_edges:
                    used_edges.append(e)
                    seen_edges.add(e["id"])
                    node_ids.add(e["source"])
                    node_ids.add(e["target"])
            citations = self._format_citations(node_ids, used_edges)
            channels_txt = "belirtilmemiş"
            width_txt = "belirtilmemiş"
            if cfg:
                is_dual = cfg.get("is_dual")
                w1 = cfg.get("gpio_width")
                w2 = cfg.get("gpio2_width")
                if is_dual == 1:
                    channels_txt = "2 kanal"
                    if w1 is not None and w2 is not None:
                        width_txt = f"kanal1={w1} bit, kanal2={w2} bit"
                    elif w1 is not None:
                        width_txt = f"{w1} bit"
                elif is_dual == 0:
                    channels_txt = "1 kanal"
                    if w1 is not None:
                        width_txt = f"{w1} bit"
                else:
                    if w2 is not None:
                        channels_txt = "2 kanal"
                    elif w1 is not None:
                        channels_txt = "1 kanal"
                    if w1 is not None and w2 is not None:
                        width_txt = f"kanal1={w1} bit, kanal2={w2} bit"
                    elif w1 is not None:
                        width_txt = f"{w1} bit"
            if ordered:
                answer = (
                    f"AXI GPIO konfigürasyonu: {channels_txt}, GPIO genişliği: {width_txt}. "
                    "LED pin atamaları: "
                    + ", ".join(ordered)
                    + "."
                )
            else:
                answer = "LED pin ataması için doğrudan kanıt bulunamadı."
        elif self._is_address_question(question):
            focus = self._address_focus_nodes(scope)
            focus_node_ids: Set[str] = set()
            aw_signals: Set[str] = set()
            ar_signals: Set[str] = set()
            segments: Set[str] = set()
            bases: Set[str] = set()
            q_lower = question.lower()
            gpio_focus = "gpio" in q_lower

            for nid, meta in focus["signals"]:
                focus_node_ids.add(nid)
                attrs = meta.get("attributes", {}) or {}
                sig = str(attrs.get("signal", "")).lower()
                if "awaddr" in sig:
                    aw_signals.add("s_axi_awaddr")
                if "araddr" in sig:
                    ar_signals.add("s_axi_araddr")
            for nid, meta in focus["segments"]:
                attrs = meta.get("attributes", {}) or {}
                spec = str(attrs.get("spec", ""))
                seg = str(attrs.get("address_segment", ""))
                if gpio_focus and "gpio" not in f"{spec} {seg}".lower():
                    continue
                focus_node_ids.add(nid)
                m = re.search(r"addr_seg=([A-Za-z0-9_/\.\-]+)", spec)
                if m:
                    segments.add(m.group(1))
                if seg:
                    segments.add(seg)
            for nid, meta in focus["maps"]:
                attrs = meta.get("attributes", {}) or {}
                base = str(attrs.get("base_address", "")).strip()
                per = str(attrs.get("peripheral", ""))
                spec = str(attrs.get("spec", ""))
                if gpio_focus and "gpio" not in f"{per} {spec}".lower():
                    continue
                focus_node_ids.add(nid)
                if base:
                    bases.add(base)

            node_ids.update(focus_node_ids)
            extra_edges = self._collect_one_hop(
                focus_node_ids,
                {"VERIFIED_BY", "CONSTRAINED_BY", "DEPENDS_ON"},
                scope=scope,
                strict_scope=bool(scope),
                max_edges=32,
            )
            seen_edges = {e["id"] for e in used_edges}
            for e in extra_edges:
                if e["id"] not in seen_edges:
                    used_edges.append(e)
                    seen_edges.add(e["id"])
                    node_ids.add(e["source"])
                    node_ids.add(e["target"])
            citations = self._format_citations(node_ids, used_edges)

            sig_parts: List[str] = []
            if aw_signals:
                sig_parts.extend(sorted(aw_signals))
            if ar_signals:
                sig_parts.extend(sorted(ar_signals))
            seg_part = ", ".join(sorted(segments)) if segments else "belirtilmemiş"
            base_part = ", ".join(sorted(bases)) if bases else "dokümante edilmemiş"
            if sig_parts:
                answer = (
                    f"AXI4-Lite adres sinyalleri: {', '.join(sig_parts)}. "
                    f"Adres segmenti: {seg_part}. "
                    f"Base address: {base_part}."
                )
            else:
                answer = (
                    f"AXI4-Lite arayüzünde doğrudan AWADDR/ARADDR sinyal kanıtı bulunamadı. "
                    f"Adres segmenti: {seg_part}. "
                    f"Base address: {base_part}."
                )
        else:
            top_nodes = [f"{c['node_id']}({c['node_type']})" for c in citations["nodes"][:6]]
            top_edges = [f"{c['edge_type']}:{c['source']}->{c['target']}" for c in citations["edges"][:6]]
            answer = (
                f"Soru tipi: {qtype}. "
                f"Kapsam: {scope or 'GLOBAL'}. "
                f"İlgili node'lar: {', '.join(top_nodes) if top_nodes else 'yok'}. "
                f"İlgili edge'ler: {', '.join(top_edges) if top_edges else 'yok'}."
            )

        return {
            "query": question,
            "query_type": qtype,
            "answer": answer,
            "citations": citations,
            "chain_confidence": chain_conf,
            "warnings": warnings,
            "debug": {
                "query_classification": qtype,
                "scope": scope,
                "stores_queried": stores,
                "ranked_node_count": len(ranked),
                "top_rank_score": top_score,
                "focus_tokens": sorted(list(focus_tokens))[:16],
                "lexical_focus_match": lexical_focus_match,
                "anchor_ids": sorted(list(anchor_ids))[:24],
                "traversal_path": traversal_path[:24],
                "used_edge_count": len(used_edges),
            },
        }


def build_engine(backend: str, graph_path: Path, db_path: Path):
    if backend == "json":
        from fpga_rag_query_v3 import QueryEngine as JsonEngine  # local module

        payload = json.loads(graph_path.read_text(encoding="utf-8"))
        return JsonEngine(payload)
    return SQLiteQueryEngine(db_path)


def run_repl(engine) -> None:
    print("FPGA RAG interactive mode. Type 'exit' to quit.")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in {"exit", "quit", "q"}:
            break
        print(json.dumps(engine.query(q), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="FPGA RAG v4 query utility (json/sqlite dual backend)")
    parser.add_argument("--backend", choices=["json", "sqlite"], default="sqlite", help="query backend")
    parser.add_argument("--query", help="single query")
    parser.add_argument("--interactive", action="store_true", help="interactive mode")
    parser.add_argument("--graph", default=str(DEFAULT_GRAPH), help="stage6 graph json (json backend)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="sqlite db (sqlite backend)")
    args = parser.parse_args()
    if not args.query and not args.interactive:
        parser.error("Either --query or --interactive is required.")

    engine = build_engine(args.backend, Path(args.graph), Path(args.db))
    try:
        if args.query:
            print(json.dumps(engine.query(args.query), ensure_ascii=False, indent=2))
        if args.interactive:
            run_repl(engine)
    finally:
        if isinstance(engine, SQLiteQueryEngine):
            engine.close()


if __name__ == "__main__":
    main()
