"""Risk Miner CLI.

  riskminer scrape <source> [--since D] [--until D] [--limit N] [--only a,b] [--no-db] [--opt k=v ...]
  riskminer parse <source>                 # raw -> data/derived/<source>/records.jsonl (no network)
  riskminer load <source>                  # manifest -> source rows, derived records -> DB
  riskminer load-all                       # XLSX + BZP copy + derive + link 22/22 (+ scraped sources)
  riskminer import-xlsx | import-bzp-copy [--limit N] | derive-bzp | link-pilot
  riskminer worker                         # job loop (SELECT ... FOR UPDATE SKIP LOCKED)
  riskminer enqueue <kind> [--payload JSON]
  riskminer report                         # docs/test_report_sources.md + exports/sources_summary.csv
  riskminer sources                        # list connectors
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys


def _opts(pairs: list[str] | None) -> dict:
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="riskminer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scrape")
    s.add_argument("source")
    s.add_argument("--since")
    s.add_argument("--until")
    s.add_argument("--limit", type=int)
    s.add_argument("--only", help="comma-separated ids")
    s.add_argument("--no-db", action="store_true", help="do not record ingestion_run / load into DB")
    s.add_argument("--opt", action="append", help="extra connector option k=v (JSON value)")

    p = sub.add_parser("parse")
    p.add_argument("source")

    ld = sub.add_parser("load")
    ld.add_argument("source")

    la = sub.add_parser("load-all")
    la.add_argument("--limit", type=int, help="BZP copy: only first N lines (smoke test)")
    la.add_argument("--skip-bzp", action="store_true")

    sub.add_parser("import-xlsx")
    ib = sub.add_parser("import-bzp-copy")
    ib.add_argument("--limit", type=int)
    ib.add_argument("--path")
    sub.add_parser("derive-bzp")
    sub.add_parser("link-pilot")
    sub.add_parser("derive-events")
    sub.add_parser("make-doc-sample")
    sub.add_parser("link-national")
    li = sub.add_parser("link-imported", help="imported records: checks, BZP link, risk events (after an import)")
    li.add_argument("--rm-ids", required=True, help="comma-separated record ids, e.g. RM-2026-023")
    ir = sub.add_parser("import-record", help="import agent without the UI: inspect, map, test, approve, run, link")
    ir.add_argument("files", nargs="+", help="XLSX / CSV / TXT / MD / JSON / DOCX / PDF with the record(s)")
    ir.add_argument("--vat", choices=["gross", "net"], help="answer to 'netto czy brutto?' if the file has amounts")
    ir.add_argument("--importer", default=None, help="importer name (default: the matched format)")
    ir.add_argument("--dry-run", action="store_true", help="stop after the test run (rolled back)")
    pe = sub.add_parser("export-project", help="per-project record export (same as GET /api/projects/{id}/export.{fmt})")
    pe.add_argument("rm_id")
    pe.add_argument("--fmt", default="md", choices=["json", "md", "docx", "pdf"])
    pe.add_argument("--out", help="output file (default: exports/<rm_id>.<fmt>)")
    for c in ("derive-lengths", "geo-buyers", "quality", "refresh-rc", "derive-geo", "anchor-evidence", "assign-sectors"):
        sub.add_parser(c)
    dt = sub.add_parser("doc-text")
    dt.add_argument("--force", action="store_true", help="rebuild chunks even if the text is unchanged")
    io_ = sub.add_parser("import-ocr")
    io_.add_argument("job_dir", help="local copy of a WCSS OCR run dir (results.jsonl + text/)")
    od = sub.add_parser("ocr-doc", help="OCR one document now (Tesseract pol), re-chunk, queue document_extract")
    od.add_argument("document_id", type=int)
    od.add_argument("--no-extract", action="store_true")
    sub.add_parser("ocr-pending", help="queue document_ocr for uploaded scans still marked needs_ocr")
    dc = sub.add_parser("demo-cleanup", help="remove e2e/test uploads and [e2e] analyses (dry run unless --apply)")
    dc.add_argument("--apply", action="store_true")
    dc.add_argument("--include-raw-named", action="store_true", help="also uploads named like <16 hex>_file (script copies)")
    dc.add_argument("--anon-analyses-since", help="also analyses by anonymous visitors created since this ISO time (tooling)")
    dc.add_argument("--analysis", action="append", default=[], help="also this analysis code (repeatable)")
    sub.add_parser("worker")
    eq = sub.add_parser("enqueue")
    eq.add_argument("kind")
    eq.add_argument("--payload", default="{}")
    sub.add_parser("report")
    sub.add_parser("sources")
    sub.add_parser("seed-catalogue")

    a = ap.parse_args(argv)

    if a.cmd == "sources":
        from riskminer import connectors
        print("\n".join(connectors.available()))
        return 0
    if a.cmd == "parse":
        from riskminer.connectors import runner
        print(json.dumps(runner.parse(a.source), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "scrape":
        opts = dict(since=a.since, until=a.until, limit=a.limit,
                    only=a.only.split(",") if a.only else None, **_opts(a.opt))
        if a.no_db:
            from riskminer.connectors import runner
            stats = runner.scrape(a.source, **opts)
            stats["parse"] = runner.parse(a.source)
            print(json.dumps(stats, ensure_ascii=False, indent=1, default=str))
            return 0
        from riskminer.ingest import pipeline
        print(json.dumps(asyncio.run(pipeline.scrape_and_load(a.source, **opts)), ensure_ascii=False, indent=1, default=str))
        return 0

    from riskminer.ingest import pipeline  # DB-backed commands

    if a.cmd == "load":
        res = asyncio.run(pipeline.load_source(a.source))
    elif a.cmd == "load-all":
        res = asyncio.run(pipeline.load_all(limit=a.limit, skip_bzp=a.skip_bzp))
    elif a.cmd == "import-xlsx":
        res = asyncio.run(pipeline.import_xlsx())
    elif a.cmd == "import-bzp-copy":
        res = asyncio.run(pipeline.import_bzp_copy(limit=a.limit, path=a.path))
    elif a.cmd == "derive-bzp":
        res = asyncio.run(pipeline.derive_bzp())
    elif a.cmd == "link-pilot":
        res = asyncio.run(pipeline.link_pilot())
    elif a.cmd == "derive-events":
        res = asyncio.run(pipeline.derive_events())
    elif a.cmd == "import-ocr":
        from riskminer.db.session import raw_conn
        from riskminer.ingest import ocr_load

        async def _ocr():
            res = ocr_load.import_run(a.job_dir)
            async with raw_conn() as conn:
                res["documents_updated"] = await ocr_load.apply(conn)
            res["doctext"] = await pipeline.doc_text()
            return res
        res = asyncio.run(_ocr())
    elif a.cmd == "ocr-doc":
        from riskminer.ingest import ocr_doc
        res = asyncio.run(ocr_doc.ocr_document(a.document_id, actor="cli", extract=not a.no_extract))
    elif a.cmd == "demo-cleanup":
        from riskminer.db.session import raw_conn
        from riskminer.ingest import demo_cleanup

        async def _dc():
            async with raw_conn() as conn:
                return await demo_cleanup.run(conn, apply=a.apply, include_raw_named=a.include_raw_named, actor="cli",
                                             anon_analyses_since=a.anon_analyses_since, analysis_codes=a.analysis)
        res = asyncio.run(_dc())
    elif a.cmd == "ocr-pending":
        from riskminer.ingest import ocr_doc
        res = asyncio.run(ocr_doc.enqueue_pending())
    elif a.cmd in ("derive-lengths", "geo-buyers", "quality", "refresh-rc", "derive-geo", "anchor-evidence",
                   "assign-sectors"):
        res = asyncio.run(getattr(pipeline, a.cmd.replace("-", "_"))())
    elif a.cmd == "link-national":
        res = asyncio.run(pipeline.link_national())
    elif a.cmd == "link-imported":
        res = asyncio.run(pipeline.link_imported(rm_ids=[x.strip() for x in a.rm_ids.split(",") if x.strip()]))
    elif a.cmd == "import-record":
        from riskminer.imports import cli_run
        res = asyncio.run(cli_run.run(a.files, vat=a.vat, importer=a.importer, dry_run=a.dry_run))
    elif a.cmd == "export-project":
        from riskminer.api import project_export
        res = asyncio.run(project_export.export_to_file(a.rm_id, a.fmt, a.out))
    elif a.cmd == "doc-text":
        res = asyncio.run(pipeline.doc_text(force=a.force))
    elif a.cmd == "make-doc-sample":
        from riskminer.ingest import sample
        res = asyncio.run(pipeline._stage("doc_sample", "derive", {}, sample.run))
    elif a.cmd == "seed-catalogue":
        res = asyncio.run(pipeline.seed_catalogue())
    elif a.cmd == "report":
        from riskminer.ingest import report
        res = asyncio.run(report.generate())
    elif a.cmd == "worker":
        from riskminer.jobs import worker
        asyncio.run(worker.run_forever())
        return 0
    elif a.cmd == "enqueue":
        from riskminer.jobs import worker
        res = asyncio.run(worker.enqueue(a.kind, json.loads(a.payload)))
    else:
        ap.print_help()
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
