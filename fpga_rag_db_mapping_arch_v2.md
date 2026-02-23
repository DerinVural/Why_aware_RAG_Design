# FPGA RAG v2 -> SQLite Mapping

Bu doküman `fpga_rag_architecture_v2.md` (v2 prensipleri) temel alınarak hazırlanan DB şemasının hangi aşamayı hangi tabloya yazdığını özetler.

## Aşama -> Tablo

- Aşama 1 (Proje Tarama)
  - `projects`
  - `stage1_project_manifest`
  - `stage1_files`
  - `pipeline_stage_runs` (stage=1)

- Aşama 2 + 3 + 6 (Graph Commit)
  - `nodes`
  - `node_attribute_kv`
  - `node_provenance_sources`
  - `edges`
  - `edge_attribute_kv`
  - `edge_provenance_sources`
  - `vector_documents`
  - `vector_provenance_sources`
  - `vector_fts`
  - `graph_commits`
  - `pipeline_stage_runs` (stage=6)

- Aşama 4 (Requirement <-> Component Matching)
  - `stage4_matches`
  - `edges.match_id`, `edges.match_strategy`
  - `pipeline_stage_runs` (stage=4)

- Aşama 5 (Gap / Orphan / Contradiction)
  - `stage5_findings`
  - `stage5_metrics`
  - `pipeline_stage_runs` (stage=5)

## Mimari v2 Zorunlu Alanları

- Confidence:
  - `nodes.confidence`
  - `edges.confidence`
  - `vector_documents.confidence`
  - `stage4_matches.confidence`

- Provenance:
  - `nodes.provenance_json` + `node_provenance_sources`
  - `edges.provenance_json` + `edge_provenance_sources`
  - `vector_documents.provenance_json` + `vector_provenance_sources`

- Stage 3 kalite alanları:
  - `nodes.version`
  - `nodes.last_updated`
  - `nodes.parse_uncertain`

- Stage 4 eşleşme alanları:
  - `stage4_matches.match_id`
  - `stage4_matches.match_strategy`
  - `stage4_matches.match_evidence_json`
  - `stage4_matches.unmatched_aspects_json`
  - `stage4_matches.primary_edge_id`

## Ana Dosyalar

- Şema: `fpga_rag_schema_arch_v2.sql`
- Loader: `fpga_rag_sqlite_loader_v2.py`
- Üretilen DB: `fpga_rag_v2_outputs/fpga_rag_arch_v2.sqlite`
