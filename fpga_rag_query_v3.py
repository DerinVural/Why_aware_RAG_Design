#!/usr/bin/env python3
"""FPGA RAG v3 query-side utility.

Implements (Phase 1 + Phase 2):
1) Query Router (WHAT/WHY/TRACE/CROSSREF) with token-level matching
2) Anti-hallucination gates (no-evidence/no-answer + scope filtering)
3) Structured response generation with warnings
4) TRACE req-tree traversal (DECOMPOSES_TO)
5) WHY traversal (MOTIVATED_BY, CHOSE, ALTERNATIVE_TO)
6) chain_confidence computation (minimum confidence in cited chain)
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "fpga_rag_v2_outputs"
DEFAULT_GRAPH = OUT_DIR / "stage6_graph_vector_commit_v3.json"

CONF_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
RANK_CONF = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}


def tokenize(text: str) -> Set[str]:
    parts = re.findall(r"[a-zA-Z0-9_çğıöşüÇĞİÖŞÜ]{2,}", text.lower())
    return set(parts)


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
    has_dma = any(k in q for k in ["project-a", "project a", "dma", "nexys-a7", "nexys a7"])
    has_axi = any(k in q for k in ["project-b", "project b", "axi_example", "axi example"])
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


class QueryEngine:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.nodes: List[Dict[str, Any]] = payload["graph"]["nodes"]
        self.edges: List[Dict[str, Any]] = payload["graph"]["edges"]
        self.node_by_id: Dict[str, Dict[str, Any]] = {n["id"]: n for n in self.nodes}
        self.node_tokens: Dict[str, Set[str]] = {
            n["id"]: tokenize(self._node_text(n)) for n in self.nodes
        }
        self.out_adj: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.in_adj: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.edges_by_type: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        for e in self.edges:
            self.out_adj[e["source"]].append(e)
            self.in_adj[e["target"]].append(e)
            self.edges_by_type[e["edge_type"]].append(e)

        self.semantic_mode = "vector_fallback"
        self.semantic_node_ids: List[str] = [n["id"] for n in self.nodes]
        self.semantic_texts: List[str] = []
        vector_docs = payload.get("vector_documents", [])
        vector_text_by_node: Dict[str, str] = {}
        for vd in vector_docs:
            nid = vd.get("node_id")
            txt = vd.get("text")
            if isinstance(nid, str) and isinstance(txt, str):
                vector_text_by_node[nid] = txt
        for nid in self.semantic_node_ids:
            if nid in vector_text_by_node:
                self.semantic_texts.append(vector_text_by_node[nid])
            else:
                self.semantic_texts.append(self._node_text(self.node_by_id[nid]))

        self.vectorizer: Optional[Any] = None
        self.tfidf_matrix: Optional[Any] = None
        if SKLEARN_AVAILABLE:
            try:
                self.vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2))
                self.tfidf_matrix = self.vectorizer.fit_transform(self.semantic_texts)
                self.semantic_mode = "vector_tfidf_cosine"
            except Exception:
                self.vectorizer = None
                self.tfidf_matrix = None
                self.semantic_mode = "vector_fallback"

    def _node_text(self, node: Dict[str, Any]) -> str:
        parts = [node.get("id", ""), node.get("name", ""), node.get("node_type", "")]
        attrs = node.get("attributes", {})
        for k, v in attrs.items():
            if isinstance(v, (str, int, float)):
                parts.append(f"{k}:{v}")
            elif isinstance(v, list):
                parts.extend([str(x) for x in v[:8]])
            elif isinstance(v, dict):
                parts.extend([f"{ik}:{iv}" for ik, iv in list(v.items())[:8]])
        return " ".join(parts)

    def _semantic_scores(self, query: str) -> Dict[str, float]:
        if not self.vectorizer or self.tfidf_matrix is None:
            return {}
        try:
            qv = self.vectorizer.transform([query])
            sims = cosine_similarity(qv, self.tfidf_matrix).ravel()
        except Exception:
            return {}
        out: Dict[str, float] = {}
        for idx, score in enumerate(sims):
            if score > 0:
                out[self.semantic_node_ids[idx]] = float(score)
        return out

    def _rank_nodes(self, query: str, scope: Optional[str], limit: int = 12) -> List[Tuple[float, Dict[str, Any]]]:
        q_tokens = tokenize(query)
        sem = self._semantic_scores(query)
        candidates = self.nodes
        if scope:
            candidates = [n for n in self.nodes if n.get("project_id") == scope]
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for n in candidates:
            overlap = float(len(q_tokens & self.node_tokens[n["id"]]))
            sem_score = float(sem.get(n["id"], 0.0))
            combined = overlap + (sem_score * 5.0)
            if overlap <= 0 and sem_score < 0.05:
                continue
            scored.append((combined, n))
        scored.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
        return scored[:limit]

    def _extract_ids(self, query: str) -> List[str]:
        ids: List[str] = []
        reqs = re.findall(r"(DMA-REQ-L[0-2]-\d{3}|AXI-REQ-L[0-2]-\d{3})", query, re.IGNORECASE)
        decs = re.findall(r"(DMA-DEC-\d{3}|AXI-DEC-\d{3})", query, re.IGNORECASE)
        for x in reqs + decs:
            ids.append(f"STAGE3:{x.upper()}")
        return ids

    def _filter_edge_scope(self, edge: Dict[str, Any], scope: Optional[str]) -> bool:
        if not scope:
            return True
        src = self.node_by_id.get(edge["source"])
        dst = self.node_by_id.get(edge["target"])
        if not src or not dst:
            return True
        if src.get("project_id") == scope or dst.get("project_id") == scope:
            return True
        return False

    def _collect_one_hop(
        self,
        anchor_ids: Set[str],
        edge_types: Optional[Set[str]],
        scope: Optional[str],
        max_edges: int = 48,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for aid in anchor_ids:
            for e in self.out_adj.get(aid, []) + self.in_adj.get(aid, []):
                if edge_types and e["edge_type"] not in edge_types:
                    continue
                if not self._filter_edge_scope(e, scope):
                    continue
                if e["id"] in seen:
                    continue
                seen.add(e["id"])
                out.append(e)
                if len(out) >= max_edges:
                    return out
        return out

    def _trace_req_tree(
        self,
        anchor_reqs: Set[str],
        scope: Optional[str],
        max_depth: int = 3,
    ) -> Tuple[Set[str], List[Dict[str, Any]], List[str]]:
        req_nodes: Set[str] = set()
        edges: List[Dict[str, Any]] = []
        traversal: List[str] = []
        seen_edges: Set[str] = set()
        q: deque[Tuple[str, int]] = deque((r, 0) for r in sorted(anchor_reqs))
        visited: Set[str] = set(anchor_reqs)
        req_nodes.update(anchor_reqs)

        while q:
            cur, depth = q.popleft()
            if depth >= max_depth:
                continue
            # Traverse both directions for L0<->L1<->L2 traceability.
            neighbors = self.out_adj.get(cur, []) + self.in_adj.get(cur, [])
            for e in neighbors:
                if e["edge_type"] != "DECOMPOSES_TO":
                    continue
                if not self._filter_edge_scope(e, scope):
                    continue
                if e["id"] not in seen_edges:
                    seen_edges.add(e["id"])
                    edges.append(e)
                    traversal.append(f"{e['source']} -DECOMPOSES_TO-> {e['target']}")
                nxt = e["target"] if e["source"] == cur else e["source"]
                nnode = self.node_by_id.get(nxt)
                if not nnode or nnode.get("node_type") != "REQUIREMENT":
                    continue
                req_nodes.add(nxt)
                if nxt not in visited:
                    visited.add(nxt)
                    q.append((nxt, depth + 1))

        # Pull implementation/evidence/constraint/issue edges from traced requirement set.
        related_types = {"IMPLEMENTS", "VERIFIED_BY", "CONSTRAINED_BY", "CONTRADICTS"}
        for rid in sorted(req_nodes):
            for e in self.out_adj.get(rid, []) + self.in_adj.get(rid, []):
                if e["edge_type"] not in related_types:
                    continue
                if not self._filter_edge_scope(e, scope):
                    continue
                if e["id"] in seen_edges:
                    continue
                seen_edges.add(e["id"])
                edges.append(e)
        return req_nodes, edges[:64], traversal[:64]

    def _why_traversal(
        self,
        anchor_decisions: Set[str],
        scope: Optional[str],
    ) -> Tuple[Set[str], List[Dict[str, Any]], List[str]]:
        node_ids: Set[str] = set(anchor_decisions)
        edges: List[Dict[str, Any]] = []
        traversal: List[str] = []
        seen_edges: Set[str] = set()

        # Decision -> requirement motivation and choice graph.
        first_types = {"MOTIVATED_BY", "CHOSE", "ALTERNATIVE_TO", "CONTRADICTS"}
        frontier: Set[str] = set(anchor_decisions)
        for _ in range(2):
            next_frontier: Set[str] = set()
            for nid in sorted(frontier):
                for e in self.out_adj.get(nid, []) + self.in_adj.get(nid, []):
                    if e["edge_type"] not in first_types:
                        continue
                    if not self._filter_edge_scope(e, scope):
                        continue
                    if e["id"] in seen_edges:
                        continue
                    seen_edges.add(e["id"])
                    edges.append(e)
                    traversal.append(f"{e['source']} -{e['edge_type']}-> {e['target']}")
                    node_ids.add(e["source"])
                    node_ids.add(e["target"])
                    next_frontier.add(e["source"])
                    next_frontier.add(e["target"])
            frontier = next_frontier
        return node_ids, edges[:64], traversal[:64]

    def _format_citations(self, node_ids: Set[str], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
        node_cits: List[Dict[str, Any]] = []
        for nid in sorted(node_ids):
            n = self.node_by_id.get(nid)
            if not n:
                continue
            node_cits.append(
                {
                    "node_id": nid,
                    "node_type": n.get("node_type"),
                    "confidence": normalize_conf(n.get("confidence")),
                    "text": n.get("name", ""),
                }
            )
        edge_cits: List[Dict[str, Any]] = []
        for e in edges:
            edge_cits.append(
                {
                    "edge_id": e["id"],
                    "edge_type": e["edge_type"],
                    "source": e["source"],
                    "target": e["target"],
                    "confidence": normalize_conf(e.get("confidence")),
                }
            )
        return {"nodes": node_cits[:24], "edges": edge_cits[:48]}

    def query(self, question: str) -> Dict[str, Any]:
        qtype = route_query(question)
        scope = detect_scope(question, qtype)
        ranked = self._rank_nodes(question, scope=scope, limit=12)
        top_score = ranked[0][0] if ranked else 0
        explicit_ids = self._extract_ids(question)

        anchor_ids: Set[str] = set(explicit_ids)
        anchor_ids.update([n["id"] for _, n in ranked[:6]])
        if scope:
            anchor_ids = {nid for nid in anchor_ids if self.node_by_id.get(nid, {}).get("project_id") == scope}

        node_ids: Set[str] = set(anchor_ids)
        used_edges: List[Dict[str, Any]] = []
        traversal_path: List[str] = []
        stores = ["graph", self.semantic_mode]

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
                scope=None,  # crossref should be global
                max_edges=64,
            )
            if len(used_edges) < 3:
                qtok = tokenize(question)
                seen = {e["id"] for e in used_edges}
                for e in self.edges:
                    if e["edge_type"] not in {"ANALOGOUS_TO", "REUSES_PATTERN", "CONTRADICTS", "INFORMED_BY"}:
                        continue
                    if e["id"] in seen:
                        continue
                    src = self.node_by_id.get(e["source"], {})
                    dst = self.node_by_id.get(e["target"], {})
                    src_tok = self.node_tokens.get(src.get("id", ""), set())
                    dst_tok = self.node_tokens.get(dst.get("id", ""), set())
                    # Fallback: keep all cross edges if query is generic, else use token overlap.
                    if any(k in question.lower() for k in ["iki proje", "cross", "çapraz"]):
                        used_edges.append(e)
                        seen.add(e["id"])
                    elif len(qtok & (src_tok | dst_tok)) >= 1:
                        used_edges.append(e)
                        seen.add(e["id"])
                    if len(used_edges) >= 64:
                        break
        else:
            used_edges = self._collect_one_hop(anchor_ids, None, scope=scope, max_edges=48)

        for e in used_edges:
            node_ids.add(e["source"])
            node_ids.add(e["target"])

        # Anti-hallucination gate with stricter conditions.
        existence_query = ("var mı" in question.lower()) or ("var mi" in question.lower())
        node_types = {self.node_by_id.get(nid, {}).get("node_type", "") for nid in node_ids}
        has_technical_node = bool(node_types & {"COMPONENT", "CONSTRAINT", "EVIDENCE", "PATTERN", "ISSUE"})

        gate_pass = bool(node_ids or used_edges)
        if qtype in {"WHY", "TRACE", "CROSSREF"}:
            gate_pass = gate_pass and len(used_edges) > 0
        if existence_query and not has_technical_node:
            gate_pass = False
        if top_score < 0.2 and not explicit_ids:
            gate_pass = False

        warnings: List[str] = []
        contradiction_edges = [e for e in used_edges if e["edge_type"] == "CONTRADICTS"]
        if contradiction_edges:
            warnings.append(f"CONTRADICTION_PRESENT:{len(contradiction_edges)}")
        if top_score <= 1:
            warnings.append("WEAK_EVIDENCE:low_query_overlap")

        confidences: List[str] = []
        for nid in node_ids:
            if nid in self.node_by_id:
                confidences.append(normalize_conf(self.node_by_id[nid].get("confidence")))
        confidences += [normalize_conf(e.get("confidence")) for e in used_edges]
        chain_conf = min_confidence(confidences)
        if chain_conf != "HIGH":
            warnings.append(f"LOW_CHAIN_CONFIDENCE:{chain_conf}")

        citations = self._format_citations(node_ids, used_edges)

        if not gate_pass:
            answer = "Bu bilgi veritabanında bulunamadı."
            citations = {"nodes": [], "edges": []}
            chain_conf = "MEDIUM"
            warnings.append("NO_EVIDENCE_GATE_TRIGGERED")
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
                "anchor_ids": sorted(list(anchor_ids))[:24],
                "traversal_path": traversal_path[:24],
                "used_edge_count": len(used_edges),
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="FPGA RAG v3 query-side utility (Phase1+Phase2+Phase3)")
    parser.add_argument("--query", help="Natural language question")
    parser.add_argument("--interactive", action="store_true", help="Interactive REPL mode")
    parser.add_argument("--graph", default=str(DEFAULT_GRAPH), help="Stage6 graph+vector commit JSON")
    args = parser.parse_args()

    if not args.query and not args.interactive:
        parser.error("Either --query or --interactive must be provided.")

    payload = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    engine = QueryEngine(payload)

    if args.query:
        result = engine.query(args.query)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.interactive:
        print("FPGA RAG v3 interactive mode. Type 'exit' to quit.")
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
            result = engine.query(q)
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
