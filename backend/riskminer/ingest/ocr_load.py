"""Bring OCR results from the WCSS batch job (scripts/wcss/ocr.sbatch) into the case base.

import_run(job_dir): for every OCR'd document, store the text as a DERIVED file next to the source's raw data
  (data/raw/<source>/<date>/ocr/<sha16>.ocr.txt) with one manifest line (method=tesseract, job id, service,
  mean confidence), and append the mapping to data/derived/ocr/results.jsonl (keyed by the PDF's sha256).
apply(conn): set document.ocr / data.ocr_text_path / data.ocr_confidence from that mapping, matched by sha256,
  so the information survives connector reloads. doctext then prefers data.ocr_text_path over the empty
  pdftotext output. Low-confidence OCR (< 0.6) is flagged for the NIECZYTELNY evidence state.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from riskminer.config import REPO_ROOT, settings
from riskminer.connectors.base import RawStore, request_key, sha256_bytes

LOW_CONF = 0.6


def _map_path() -> Path:
    return Path(settings().data_dir) / "derived" / "ocr" / "results.jsonl"


def import_run(job_dir: str | Path, service: str = "hpc-dawlin1140-1773687823 (PBR)") -> dict:
    job_dir = Path(job_dir)
    job_id = job_dir.name
    results = [json.loads(line) for line in (job_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    mp = _map_path()
    mp.parent.mkdir(parents=True, exist_ok=True)
    known = set()
    if mp.exists():
        for line in mp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                known.add(json.loads(line)["sha256"])
    stores: dict[str, RawStore] = {}
    run_id = str(uuid.uuid4())
    n = skipped = 0
    with mp.open("a", encoding="utf-8") as out:
        for r in results:
            if r.get("status") not in ("ok", "partial"):
                skipped += 1
                continue
            txt = job_dir / "text" / f"{r['document_id']}.ocr.txt"
            if not txt.exists():
                skipped += 1
                continue
            sha = r.get("sha256") or ""
            if sha and sha in known:
                continue
            src = r.get("source") or "ocr"
            store = stores.setdefault(src, RawStore(src))
            content = txt.read_bytes()
            rel_name = f"ocr/{(sha or r['document_id'])[:16]}.ocr.txt"
            p = store.path_for(rel_name)
            p.write_bytes(content)
            rel = store.rel(p)
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            store.append({
                "source": src, "fetched_at": now, "method": "tesseract", "url": f"ocr:{r['path']}", "params": {},
                "http_status": None, "content_type": "text/plain", "bytes": len(content), "sha256": sha256_bytes(content),
                "path": rel, "licence": "derived (OCR of a public document)", "run_id": run_id, "status": "ok",
                "note": (f"OCR tesseract -l pol --psm 1 at 300 dpi; WCSS job {job_id}, service {service}; "
                         f"pages={r.get('pages')} mean_conf={r.get('mean_conf')}; source_sha256={sha}"),
                "key": request_key("DERIVED", f"ocr:{r['path']}", {"job": job_id}),
            })
            out.write(json.dumps({"sha256": sha, "path": r["path"], "source": src, "ocr_text_path": rel,
                                  "ocr_confidence": r.get("mean_conf"), "pages": r.get("pages"), "job": job_id,
                                  "status": r.get("status")}, ensure_ascii=False) + "\n")
            known.add(sha)
            n += 1
    return {"imported": n, "skipped": skipped, "results": len(results), "job": job_id}


async def apply(conn) -> int:
    mp = _map_path()
    if not mp.exists():
        return 0
    rows = []
    for line in mp.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            if d.get("sha256"):
                rows.append((d["sha256"], d["path"], d["ocr_text_path"], d.get("ocr_confidence"), d.get("job")))
    if not rows:
        return 0
    async with conn.transaction():
        await conn.execute("CREATE TEMP TABLE tmp_ocr (sha256 text, path text, ocr_text_path text, conf float8, job text) "
                           "ON COMMIT DROP")
        await conn.copy_records_to_table("tmp_ocr", records=rows)
        r = await conn.execute(f"""
            UPDATE document d SET ocr = true,
                   data = d.data || jsonb_build_object('ocr_text_path', t.ocr_text_path, 'ocr_confidence', t.conf,
                                                       'ocr_job', t.job, 'needs_ocr', false, 'ocr_done', true,
                                                       'ocr_low_confidence', coalesce(t.conf, 0) < {LOW_CONF})
            FROM tmp_ocr t
            WHERE (d.sha256 = t.sha256 OR d.path = t.path)
              AND (d.data->>'ocr_text_path' IS DISTINCT FROM t.ocr_text_path OR NOT d.ocr)""")
    return int(r.split()[-1])


__all__ = ["import_run", "apply", "REPO_ROOT"]
