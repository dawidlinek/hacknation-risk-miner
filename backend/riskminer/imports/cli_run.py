"""`riskminer import-record <files>`: the import agent without the UI (fallback for the organizers' live test).

Same service functions and the same order as the Import screen (upload, inspect, propose mapping, answer, test run,
approve, run), then the link stage that the `import_mapped` job runs. Prints what the screen would show."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from riskminer.db.session import sessionmaker
from riskminer.imports import service as S

ACTOR = "user:Ekspert (demo)"


class _Upload:
    """Minimal async stream like FastAPI's UploadFile.read()."""

    def __init__(self, path: Path):
        self._f = path.open("rb")

    async def read(self, n: int = -1) -> bytes:
        b = self._f.read(n)
        if not b:
            self._f.close()
        return b


async def run(files: list[str], *, vat: str | None = None, importer: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    paths = [Path(f).expanduser().resolve() for f in files]
    for p in paths:
        if not p.is_file():
            raise SystemExit(f"no such file: {p}")
    out: dict[str, Any] = {}
    async with sessionmaker()() as db:
        created = await S.create(db, [(p.name, _Upload(p)) for p in paths], ACTOR, "cli")
        code = created["code"]
        out["code"] = code
        st = await S.inspect(db, code, ACTOR, "cli")
        out["tool_calls"] = [f"{c['call']}: {c['out']}" for c in st["tool_calls"]]
        st = await S.propose_mapping(db, code, ACTOR, "cli")
        if isinstance(st, dict) and st.get("error"):
            await db.commit()
            return {**out, "error": st["error"]}
        out["mapping"] = {m["column"]: f"{m.get('field')} ({m['status']})" for m in st["mapping"]}
        if st["questions"]:
            if not vat:
                await db.commit()
                return {**out, "error": "the file has amounts: rerun with --vat gross or --vat net", "questions": st["questions"]}
            st = await S.answer(db, code, {"value_vat_basis": vat}, ACTOR, "cli")
        tr = await S.test_run(db, code, 500, ACTOR, "cli")
        out["test_run"] = {k: tr.get(k) for k in ("rows", "ok", "failed", "would", "failures")} if isinstance(tr, dict) else tr
        await db.commit()
        if dry_run or (isinstance(tr, dict) and tr.get("error")):
            return out
        name = importer or ((st.get("importer") or {}).get("name") if isinstance(st, dict) else None) or "importer"
        out["approve"] = await S.approve(db, code, name, ACTOR, "cli")
        await db.commit()
        res = await S.full_run(db, code)
        await db.commit()
    out["run"] = {k: res.get(k) for k in ("rows", "ok", "failed", "inserted", "updated", "protected_skipped", "projects")}
    if res.get("projects"):
        from riskminer.ingest import pipeline
        out["link"] = await pipeline.link_imported(rm_ids=res["projects"])
    out["next"] = [f"card: /projekty/{rm}  export: uv run riskminer export-project {rm} --fmt pdf" for rm in res.get("projects") or []]
    return out
