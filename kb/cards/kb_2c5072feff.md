---
anonymization:
  placeholders_used:
  - '[CLIENT]'
  - '[FEE]'
  status: anonymized
canonical_block: false
canonical_doc_id: cd_775a5a8812d8
chunk_span:
  chars: 623
  elements: 1
content_origin: source_text
doc_kind: section_exemplar
doc_path:
- Integration Approach
extraction_status: clean
grain: chunk
identity:
  content_hash: 2c5072feff581b5cb563e8819d042d8cdc6939e429309f00d7210850ba911a8d
  source_hash: 775a5a8812d83423f032694d2131a0929df9ea81f3c21a07fda61a7ba04618d5
  structural_key: Integration Approach#0
kb_id: kb_2c5072feff
layer: corpus
legal_hold: false
outcome: won
section_types:
- integration_approach
sensitivity: internal
summary: 'Interface inventory and HL7 v2 / FHIR R4 integration approach for a hospital ERP: contract sheets, retirement of duplicative feeds, payroll-dependency sequencing.

  Open for the interface contract-sheet fields.'
title: Integration Approach
type_tags:
- integration
use_restriction: false
version: 1
---
For [CLIENT] we inventoried ninety-four interfaces on the
legacy platform and retired thirty-one of them as duplicative before design
began. Clinical boundary systems exchanged ADT and charge data over HL7 v2
feeds through the existing integration engine; the new ERP consumed FHIR
R4 resources for practitioner and location synchronization. Every interface
carried a contract sheet: source of truth, direction, frequency, error
queue owner, and reprocessing procedure. Interface development was
sequenced by payroll dependency, not by system age. The integration
workstream was priced within the program's [FEE] fixed fee.
