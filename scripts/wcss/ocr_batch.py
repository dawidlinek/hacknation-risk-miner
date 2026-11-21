"""Batch OCR of scanned PDFs (Tesseract, Polish model) for Risk Miner, run inside a WCSS CPU job.

Input:  <in_dir>/ocr_input.tsv (document_id, source, repo-relative path, sha256) + the PDFs at those paths.
Output: <out_dir>/text/<document_id>.ocr.txt  (pages separated by \f, like pdftotext)
        <out_dir>/results.jsonl                (one line per document: pages, mean confidence, status, timings)

Pages are the unit of work (load balancing across cores). Each tesseract call is single-threaded
(OMP_THREAD_LIMIT=1) so `--workers` processes use exactly the allocated cores. Licences: tesseract and the
tessdata models are Apache-2.0, pypdfium2 is Apache-2.0/BSD; nothing AGPL (no OCRmyPDF/Ghostscript).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DPI = 300
FAIL_FAST_PAGES = 100        # abort when this many pages finished and none succeeded
MAX_PIXELS = 24_000_000      # A3 at 300 dpi is ~17 Mpx; A0 drawings are rendered at lower dpi instead of 140 Mpx


def ocr_page(task: tuple[str, str, int, str, float]) -> tuple[str, int, str, float | None, str]:
    """(doc_id, pdf_path, page_index, lang, pixel_factor) -> (doc_id, page_index, text, mean_conf, error)."""
    import math

    import pypdfium2 as pdfium

    doc_id, path, i, lang, factor = task
    try:
        pdf = pdfium.PdfDocument(path)
        page = pdf[i]
        w_pt, h_pt = page.get_size()
        scale = DPI / 72
        cap = MAX_PIXELS * factor
        if w_pt * h_pt * scale * scale > cap:
            scale = math.sqrt(cap / max(1.0, w_pt * h_pt))
        img = page.render(scale=scale, grayscale=True).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page.close()
        pdf.close()
        with tempfile.TemporaryDirectory() as td:
            base = os.path.join(td, "out")
            # output formats via -c variables, not the "txt"/"tsv" config files: those live in tessdata/configs,
            # which a TESSDATA_PREFIX holding only *.traineddata does not have (job 6384411 lost every page to that)
            subprocess.run(["tesseract", "stdin", base, "-l", lang, "--psm", "1",
                            "-c", "tessedit_create_txt=1", "-c", "tessedit_create_tsv=1"],
                           input=buf.getvalue(), check=True, capture_output=True, timeout=600)
            text = Path(base + ".txt").read_text(encoding="utf-8", errors="replace")
            confs = []
            if os.path.exists(base + ".tsv"):          # confidence is optional; the text is what matters
                with open(base + ".tsv", encoding="utf-8", errors="replace") as fh:
                    for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                        try:
                            c = float(row.get("conf") or -1)
                        except ValueError:
                            continue
                        if c >= 0 and (row.get("text") or "").strip():
                            confs.append(c)
        return doc_id, i, text, (sum(confs) / len(confs) / 100.0) if confs else None, ""
    except Exception as e:  # noqa: BLE001 - recorded per page
        return doc_id, i, "", None, f"{type(e).__name__}: {e}"[:300]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=len(os.sched_getaffinity(0)))
    ap.add_argument("--lang", default="pol")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    import pypdfium2 as pdfium

    in_dir, out = Path(a.in_dir), Path(a.out_dir)
    (out / "text").mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["document_id"] for line in open(out / "results.jsonl")} if (out / "results.jsonl").exists() else set()
    docs, tasks = {}, []
    for n, (doc_id, source, rel, sha) in enumerate(csv.reader(open(in_dir / "ocr_input.tsv"), delimiter="\t")):
        if a.limit and n >= a.limit:
            break
        if doc_id in done:
            continue
        p = in_dir / rel
        try:
            k = len(pdfium.PdfDocument(str(p)))
        except Exception as e:  # noqa: BLE001
            docs[doc_id] = {"document_id": doc_id, "source": source, "path": rel, "sha256": sha, "pages": 0,
                            "status": "error", "error": f"open: {type(e).__name__}: {e}"[:300]}
            continue
        docs[doc_id] = {"document_id": doc_id, "source": source, "path": rel, "sha256": sha, "pages": k,
                        "texts": [""] * k, "confs": [None] * k, "errors": []}
        tasks += [(doc_id, str(p), i, a.lang) for i in range(k)]
    print(f"{len(docs)} documents, {len(tasks)} pages, {a.workers} workers", flush=True)
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
    from concurrent.futures.process import BrokenProcessPool

    t0 = time.time()
    remaining = {d: v["pages"] for d, v in docs.items() if v.get("pages")}
    attempts: dict[tuple[str, int], int] = {}
    todo = list(tasks)
    done_n = ok_pages = 0
    last_print = time.time()
    with open(out / "results.jsonl", "a", encoding="utf-8") as res:
        def finish(doc_id: str, i: int, text: str, conf, err: str) -> None:
            nonlocal done_n
            d = docs[doc_id]
            d["texts"][i], d["confs"][i] = text, conf
            if err:
                d["errors"].append(f"p{i + 1}: {err}")
            remaining[doc_id] -= 1
            done_n += 1
            nonlocal ok_pages
            ok_pages += 0 if err else 1
            if done_n >= FAIL_FAST_PAGES and ok_pages == 0:
                # a broken setup (missing tessdata, bad flags) fails every page: stop before the allocation burns
                raise SystemExit(f"fail-fast: first {done_n} pages all failed, last error: {err}")
            if remaining[doc_id] == 0:
                (out / "text" / f"{doc_id}.ocr.txt").write_text("\f".join(t.strip() for t in d["texts"]) + "\n",
                                                               encoding="utf-8")
                cs = [c for c in d["confs"] if c is not None]
                res.write(json.dumps({"document_id": doc_id, "source": d["source"], "path": d["path"],
                                      "sha256": d["sha256"], "pages": d["pages"],
                                      "mean_conf": round(sum(cs) / len(cs), 4) if cs else None,
                                      "chars": sum(len(t) for t in d["texts"]),
                                      "status": "ok" if not d["errors"] else ("partial" if cs else "error"),
                                      "errors": d["errors"][:5]}, ensure_ascii=False) + "\n")
                res.flush()
                del d["texts"], d["confs"]

        while todo:
            ex = ProcessPoolExecutor(max_workers=a.workers, max_tasks_per_child=200)
            inflight: dict = {}
            broken = False
            try:
                while todo or inflight:
                    while todo and len(inflight) < a.workers * 2:
                        t = todo.pop(0)
                        f = (attempts.get((t[0], t[2]), 0))
                        inflight[ex.submit(ocr_page, (*t[:4], 0.25 if f else 1.0))] = t
                    fin, _ = wait(list(inflight), timeout=60, return_when=FIRST_COMPLETED)
                    for fu in fin:
                        t = inflight.pop(fu)
                        try:
                            finish(*fu.result())
                        except BrokenProcessPool:
                            raise
                        except Exception as e:  # noqa: BLE001
                            finish(t[0], t[2], "", None, f"{type(e).__name__}: {e}"[:200])
                    if time.time() - last_print > 120 or (done_n and done_n % 500 == 0):
                        el = time.time() - t0
                        print(f"{done_n}/{len(tasks)} pages  {el:.0f}s  {done_n / max(el, 1):.1f} p/s", flush=True)
                        last_print = time.time()
            except BrokenProcessPool:
                broken = True
                # a worker died (most likely memory): retry the in-flight pages once at a quarter of the pixel cap
                for fu, t in inflight.items():
                    key = (t[0], t[2])
                    attempts[key] = attempts.get(key, 0) + 1
                    if attempts[key] >= 2:
                        finish(t[0], t[2], "", None, "worker died twice (memory?)")
                    else:
                        todo.insert(0, t)
                print(f"pool broke; retrying {sum(1 for t in inflight.values() if attempts[(t[0], t[2])] < 2)} pages",
                      flush=True)
            finally:
                ex.shutdown(wait=not broken, cancel_futures=True)
        for d in docs.values():
            if d.get("status") == "error":
                res.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"done {len(tasks)} pages in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
