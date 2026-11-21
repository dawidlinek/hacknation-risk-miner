# Dry-run records (rehearsal of the 11:00 live test, 21.11.2026 evening)

Everything below was created in the LOCAL main DB (localhost:5434) by the rehearsal. Remove it before the final dump.
Nothing else was approved, rejected or deleted. Prod (exante.linek.dev) has none of these rows.

## 1. Imported project record

| What | Id |
|---|---|
| project | `RM-DRY-2026-023` (project.id **274**), title `[dryrun] Budowa sieci kanalizacji sanitarnej w miejscowości Ruda` |
| project_procedure | id 535 (project 274 -> procedure 171434, ocds-148610-cd1dbec8-2938-4d10-bbd4-cc60465639d1, method `kpo_cited`) |
| link_candidate | id 87722 (left_table project, left_id 274) |
| import_session | IMP-2026-0002 ... IMP-2026-0010 (9 sessions; 0009 only tested) |
| importer | ids 47, 51, 52 (`zestaw organizatora` v1, v2, v3; created by the rehearsal approvals, each with one `review` approve row) |
| import jobs | job ids 1178, 1259, 1260, 1261, 1262, 1263 (`import_mapped`); IMP-0008 and IMP-0010 ran through the CLI (no job) |
| source rows (kind import) | 139422, 139438, 139439, 139440, 139442 (+ the source of IMP-2026-0010, same sha as 139422, reused) |
| ingestion_run | connector `import` and `link_import`, 8 each, started 22:07 to 22:50 UTC (ids listed by `SELECT id FROM ingestion_run WHERE connector IN ('import','link_import')`) |
| files | `data/imports/IMP-2026-0002` ... `IMP-2026-0010`, `data/raw/imports/*dryrun_rekord_projektu*` (+ their manifest lines) |

**Careful, cascade:** `risk_event.project_id` references project with ON DELETE CASCADE. The 6 BZP risk events of the Gidle
procedure (ids 30242, 15236, 23613, 30306, 32557, 32558; origin CALC, national data) were attached to project 274 by
the link stage. Detach them first, or deleting the project deletes them:

```sql
BEGIN;
UPDATE risk_event SET project_id = NULL WHERE project_id = 274;
DELETE FROM project WHERE id = 274;            -- cascades project_procedure, review_item, risk_signal, monitor_watch rows of 274
DELETE FROM link_candidate WHERE left_table = 'project' AND left_id = 274;
DELETE FROM import_session WHERE code BETWEEN 'IMP-2026-0002' AND 'IMP-2026-0010';
DELETE FROM importer WHERE id IN (47, 51, 52);  -- check no other import_session points at them first
DELETE FROM job WHERE id IN (1178, 1259, 1260, 1261, 1262, 1263);
COMMIT;
```

(`review` and `audit_log` rows stay: append-only by design.)

## 2. New-investment analyses and their documents

| What | Ids |
|---|---|
| analyses | AN-2026-0023 ... AN-2026-0037 (15 codes: 0023-0027 via API with `[dryrun]` titles, 0028-0037 via the UI rehearsal, auto titles `Kanalizacja sanitarna, ok. 7,4 km`) |
| documents (uploads) | 34433 `dryrun_opis_inwestycji.docx`, 34434 `dryrun_opis_inwestycji.pdf`, 34435 `dryrun_opis_inwestycji.txt` (all now public) |
| upload source rows | 139435, 139436, 139437 |
| pack files | `exports/packs/AN-2026-0023-*` ... `AN-2026-0037-*` (AN-2026-0023 also has older cached packs of a previous analysis with the same code) |

Cleanup with the existing tool (dry run first, then `--apply`):

```bash
cd backend
uv run riskminer demo-cleanup $(for n in $(seq 23 37); do printf -- '--analysis AN-2026-%04d ' $n; done)
# documents 34433-34435 are not "[e2e]"-named: delete them (and their pages/chunks/jobs) by id, e.g.
#   DELETE FROM job WHERE payload->>'document_id' IN ('34433','34434','34435');
#   DELETE FROM document WHERE id IN (34433, 34434, 34435);
```

## 3. Rehearsal inputs and outputs (files in git status, not DB)

- inputs: `docs/submission/dryrun_inputs/` (record as XLSX, CSV, TXT pipe, TXT fields, JSON, DOCX, PDF; description as TXT, DOCX, PDF)
- outputs: `docs/submission/dryrun_outputs/` (the two deliverables) and `docs/submission/dryrun_outputs/e2e/` (UI run downloads, timings.json)

## 4. doc import test (organizer case documents through /zrodla and the card drop zone, 21/22.11.2026 night)

Created in the LOCAL main DB by the document-import repro and verification (modified copies of the three files in
`materials/organizer_cases/`, one or more bytes appended, so the real files keep their own sha256 for the jury).
Nothing was approved or rejected.

| What | Ids |
|---|---|
| documents (uploads) | 34503 zagrodno (card RM-2026-002), 34504 grodzisko (card RM-2026-010), 34505 zlawies (card RM-2026-005); 34574 zagrodno, 34575 zławieś, 34576 grodzisko (all three via /zrodla, auto-linked to RM-2026-002 / 005 / 010) |
| sha256 of those copies | e6f33826..., 6b6194ac..., 10a453a2..., 4c1d489e..., 3ac5e0cc..., 1d70133f... (`SELECT sha256 FROM document WHERE id IN (...)`) |
| upload source rows (kind upload) | 139454, 139455, 139456, 139501, 139502, 139503 |
| import_session | IMP-2026-0011, IMP-2026-0012, IMP-2026-0013 (repro of the bug, stuck at "przejrzane"), IMP-2026-0014 (all three in one drop), IMP-2026-0015 (duplicate drop) |
| jobs | 1334-1340, 1381-1387 (`document_extract`, `document_ocr`, `document_link`) |
| review_item | 72122-72126, 72128-72142, 72333-72337, 72339-72352 (all keyed `doc:<document id>:...`); item 309 (catalogue R18) existed before and was not changed |
| risk_event | 872686-872697, 872787-872798 (keys `doc:<document id>:...`) |
| contract_change | 677691, 677692, 677719, 677720 |
| link_candidate | 87911-87915, 87983-87987 (left_table document) |
| alert | 512, 513, 514, 551, 552, 553 |
| evidence | 36 rows with document_id in the six documents |
| files | `data/imports/IMP-2026-0011` ... `IMP-2026-0015`; `data/raw/upload/<sha>.*` of the six copies (+ their manifest lines, + OCR text under `data/raw/upload/ocr/`) |

```sql
BEGIN;
-- d = the six documents
DELETE FROM evidence        WHERE document_id IN (34503,34504,34505,34574,34575,34576);
DELETE FROM review_item     WHERE key ~ '^doc:(34503|34504|34505|34574|34575|34576):';
DELETE FROM risk_event      WHERE key ~ '^doc:(34503|34504|34505|34574|34575|34576):';
DELETE FROM contract_change WHERE document_id IN (34503,34504,34505,34574,34575,34576);
DELETE FROM link_candidate  WHERE left_table = 'document' AND left_id IN (34503,34504,34505,34574,34575,34576);
DELETE FROM alert           WHERE document_id IN (34503,34504,34505,34574,34575,34576);
DELETE FROM job             WHERE payload->>'document_id' IN ('34503','34504','34505','34574','34575','34576');
DELETE FROM document        WHERE id IN (34503,34504,34505,34574,34575,34576);   -- cascades document_page, chunk
DELETE FROM source          WHERE id IN (139454,139455,139456,139501,139502,139503) AND NOT EXISTS (SELECT 1 FROM document WHERE source_id = source.id);
DELETE FROM import_session  WHERE code BETWEEN 'IMP-2026-0011' AND 'IMP-2026-0015';
COMMIT;
```

(Check the FK order on the day: if a delete is refused, the error names the referencing table. `review` and `audit_log`
rows stay: append-only by design.)
