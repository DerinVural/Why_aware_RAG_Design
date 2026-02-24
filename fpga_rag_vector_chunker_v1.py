#!/usr/bin/env python3
"""Architecture-v2 aligned vector chunker for Stage6 Graph+Vector payload.

Chunk strategy:
- Field-aware text assembly per node (identity + attributes + provenance + edge summaries + source snippets)
- Token-window fallback for oversized segments
- Overlap between chunks for semantic continuity
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "fpga_rag_v2_outputs"
DEFAULT_IN = OUT_DIR / "stage6_graph_vector_commit_v3.json"
DEFAULT_OUT = OUT_DIR / "stage6_graph_vector_commit_v4_chunked.json"

WORD_RE = re.compile(r"[a-zA-Z0-9_çğıöşüÇĞİÖŞÜ:/.\-]{1,}")
ATTR_PRIORITY = [
    "req_id",
    "decision_id",
    "title",
    "level",
    "priority",
    "status",
    "acceptance_criteria",
    "constraints",
    "kind",
    "vlnv",
    "spec",
    "detail",
    "source_file",
]


def stable_id(prefix: str, text: str) -> str:
    return prefix + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def to_words(text: str) -> List[str]:
    return WORD_RE.findall(text)


def value_to_lines(value: Any, max_items: int = 12) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out: List[str] = []
        for x in value[:max_items]:
            if isinstance(x, dict):
                out.append(json.dumps(x, ensure_ascii=False, default=str))
            else:
                out.append(str(x))
        return out
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False, default=str)]
    return [str(value)]


def source_snippet(path: str, line: Optional[int], radius: int = 1) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    if not lines:
        return None
    idx = (line - 1) if isinstance(line, int) and line > 0 else 0
    lo = max(0, idx - radius)
    hi = min(len(lines), idx + radius + 1)
    out = [f"L{n+1}: {lines[n].strip()}" for n in range(lo, hi)]
    return f"{p.name} :: " + " | ".join(out)


def chunk_words(words: List[str], max_tokens: int, overlap_tokens: int) -> List[str]:
    if len(words) <= max_tokens:
        return [" ".join(words)]
    chunks: List[str] = []
    i = 0
    stride = max(1, max_tokens - overlap_tokens)
    while i < len(words):
        j = min(len(words), i + max_tokens)
        chunks.append(" ".join(words[i:j]))
        if j >= len(words):
            break
        i += stride
    return chunks


def segment_to_chunks(
    segments: List[str],
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> List[str]:
    chunks: List[str] = []
    cur_parts: List[str] = []
    cur_count = 0

    def flush() -> None:
        nonlocal cur_parts, cur_count
        if cur_parts:
            chunks.append("\n".join(cur_parts))
            cur_parts = []
            cur_count = 0

    for seg in segments:
        seg_words = to_words(seg)
        seg_count = len(seg_words)
        if seg_count == 0:
            continue
        if seg_count > max_tokens:
            flush()
            for sub in chunk_words(seg_words, max_tokens=max_tokens, overlap_tokens=overlap_tokens):
                chunks.append(sub)
            continue
        if cur_count + seg_count > max_tokens and cur_parts:
            prev_tail = to_words("\n".join(cur_parts))[-overlap_tokens:]
            flush()
            if prev_tail:
                cur_parts.append("CONTINUATION: " + " ".join(prev_tail))
                cur_count = len(prev_tail)
        cur_parts.append(seg)
        cur_count += seg_count
    flush()
    return chunks


def node_segments(
    node: Dict[str, Any],
    out_edges: List[Dict[str, Any]],
    in_edges: List[Dict[str, Any]],
    snippet_radius: int,
) -> List[str]:
    segments: List[str] = []
    node_id = str(node.get("id", ""))
    node_type = str(node.get("node_type", ""))
    project_id = str(node.get("project_id", ""))
    name = str(node.get("name", ""))
    conf = str(node.get("confidence", "MEDIUM"))
    attrs = dict(node.get("attributes", {}) or {})
    prov = dict(node.get("provenance", {}) or {})

    segments.append(
        "\n".join(
            [
                f"NODE_ID: {node_id}",
                f"NODE_TYPE: {node_type}",
                f"PROJECT_ID: {project_id}",
                f"NAME: {name}",
                f"CONFIDENCE: {conf}",
            ]
        )
    )

    preferred = [k for k in ATTR_PRIORITY if k in attrs]
    rest = [k for k in sorted(attrs.keys()) if k not in preferred]
    for key in preferred + rest:
        lines = value_to_lines(attrs.get(key))
        if not lines:
            continue
        segments.append("\n".join([f"ATTR::{key}"] + [f"- {x}" for x in lines]))

    src_lines: List[str] = []
    for s in (prov.get("sources") or [])[:4]:
        f = s.get("file")
        l = s.get("line")
        sec = s.get("section")
        src_lines.append(f"SOURCE_REF: file={f} line={l} section={sec}")
        snip = source_snippet(str(f or ""), l if isinstance(l, int) else None, radius=snippet_radius)
        if snip:
            src_lines.append(f"SOURCE_SNIPPET: {snip}")
    if src_lines:
        segments.append("\n".join(src_lines))

    if out_edges:
        lines = [f"OUT_EDGE_COUNT: {len(out_edges)}"]
        for e in sorted(out_edges, key=lambda x: (x.get("edge_type", ""), x.get("target", "")))[:10]:
            lines.append(
                f"OUT_EDGE: {e.get('edge_type')} -> {e.get('target')} (confidence={e.get('confidence', 'MEDIUM')})"
            )
        segments.append("\n".join(lines))
    if in_edges:
        lines = [f"IN_EDGE_COUNT: {len(in_edges)}"]
        for e in sorted(in_edges, key=lambda x: (x.get("edge_type", ""), x.get("source", "")))[:10]:
            lines.append(
                f"IN_EDGE: {e.get('edge_type')} <- {e.get('source')} (confidence={e.get('confidence', 'MEDIUM')})"
            )
        segments.append("\n".join(lines))

    return segments


def build_chunked_vectors(
    payload: Dict[str, Any],
    *,
    max_tokens: int,
    overlap_tokens: int,
    snippet_radius: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    graph = payload.get("graph", {}) or {}
    nodes = list(graph.get("nodes", []) or [])
    edges = list(graph.get("edges", []) or [])

    out_by: Dict[str, List[Dict[str, Any]]] = {}
    in_by: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        out_by.setdefault(e.get("source", ""), []).append(e)
        in_by.setdefault(e.get("target", ""), []).append(e)

    vectors: List[Dict[str, Any]] = []
    node_chunk_counts: Dict[str, int] = {}
    for n in nodes:
        nid = n.get("id", "")
        segs = node_segments(
            n,
            out_edges=out_by.get(nid, []),
            in_edges=in_by.get(nid, []),
            snippet_radius=snippet_radius,
        )
        chunks = segment_to_chunks(segs, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        if not chunks:
            chunks = [f"NODE_ID: {nid}\nNAME: {n.get('name','')}\nNODE_TYPE: {n.get('node_type','')}"]
        node_chunk_counts[nid] = len(chunks)
        for idx, text in enumerate(chunks, start=1):
            prov = copy.deepcopy(n.get("provenance", {}) or {})
            prov["chunk"] = {
                "method": "field_aware_overlap_v1",
                "index": idx,
                "total": len(chunks),
                "max_tokens": max_tokens,
                "overlap_tokens": overlap_tokens,
                "snippet_radius": snippet_radius,
            }
            vectors.append(
                {
                    "vector_id": stable_id("V:", f"{nid}:chunk:{idx}:{text[:160]}"),
                    "node_id": nid,
                    "project_id": n.get("project_id"),
                    "text": text,
                    "provenance": prov,
                    "confidence": n.get("confidence", "MEDIUM"),
                }
            )

    total_nodes = len(nodes)
    total_chunks = len(vectors)
    avg_chunks = (total_chunks / total_nodes) if total_nodes else 0.0
    max_chunks = max(node_chunk_counts.values()) if node_chunk_counts else 0
    summary = {
        "method": "field_aware_overlap_v1",
        "nodes": total_nodes,
        "vector_chunks": total_chunks,
        "avg_chunks_per_node": round(avg_chunks, 3),
        "max_chunks_on_single_node": max_chunks,
        "max_tokens": max_tokens,
        "overlap_tokens": overlap_tokens,
        "snippet_radius": snippet_radius,
    }
    return vectors, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk Stage6 vector_documents with architecture-v2 aware strategy")
    parser.add_argument("--in", dest="in_path", default=str(DEFAULT_IN), help="input stage6 graph+vector json")
    parser.add_argument("--out", dest="out_path", default=str(DEFAULT_OUT), help="output chunked stage6 json")
    parser.add_argument("--max-tokens", type=int, default=120)
    parser.add_argument("--overlap-tokens", type=int, default=24)
    parser.add_argument("--snippet-radius", type=int, default=1)
    args = parser.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    vectors, summary = build_chunked_vectors(
        payload,
        max_tokens=args.max_tokens,
        overlap_tokens=args.overlap_tokens,
        snippet_radius=args.snippet_radius,
    )

    payload["vector_documents"] = vectors
    payload["schema_version"] = "fpga_rag_v4_chunked_graph_vector_commit"
    commit_meta = dict(payload.get("commit_metadata", {}) or {})
    commit_meta["vector_chunking"] = summary
    payload["commit_metadata"] = commit_meta

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote: {out_path}")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
