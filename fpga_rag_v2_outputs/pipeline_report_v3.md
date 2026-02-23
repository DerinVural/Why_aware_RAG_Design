# FPGA RAG v3 Pipeline Report
Generated: 2026-02-23T09:13:25Z

## Stage 1 - Project Scan
- PROJECT-A: 54 files
- PROJECT-B: 15 files

## Stage 2 - Entity Extraction
- PROJECT-A: COMPONENT=44 CONSTRAINT=4 EVIDENCE=24 ISSUE=5 PATTERN=3 EDGE=99
- PROJECT-B: COMPONENT=35 CONSTRAINT=24 EVIDENCE=55 ISSUE=4 PATTERN=3 EDGE=106

## Stage 3 - Requirement Graph
- PROJECT=2 REQUIREMENT=31 DECISION=10 SOURCE_DOC=20 EDGE=87
- Validation findings: 0

## Stage 4 - Matching
- matches=1500 IMPLEMENTS=909 VERIFIED_BY=472 CONSTRAINED_BY=119

## Stage 5 - Gap Analysis
- Coverage gaps: 1
- Orphan components: 0
- Constraint/timing contradictions: 3
- Cross-project edges: 8
- Stage5-derived graph nodes: 1
- Stage5-derived graph edges: 12

### Requested Special Checks
- DMA FPGA part inconsistency verified: True
- tone_generator PARSE_UNCERTAIN assessment: COMPLIANT
- Interrupt classification: decision_with_residual_issue
- axi_example educational pattern sufficiency: True
- Signal Path coverage summary:
  - AXI-REQ-L1-005: covered=True mapped_components=20
  - DMA-REQ-L1-006: covered=True mapped_components=45

