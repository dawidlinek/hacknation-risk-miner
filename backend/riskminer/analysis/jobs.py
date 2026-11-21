"""Jobs of the analysis package (picked up by riskminer.jobs.worker)."""
from __future__ import annotations

from riskminer.jobs.worker import register


@register("analysis_mark_affected")
async def analysis_mark_affected(payload: dict, job_id: int) -> dict:
    """{rm_id? | ocid?, reason, document_id?}: flag analyses that cite this case as similar (new_documents §2 step 8)."""
    from riskminer.analysis import service as SV
    from riskminer.db.session import sessionmaker

    async with sessionmaker()() as s:
        marked = await SV.mark_affected(s, rm_id=payload.get("rm_id"), ocid=payload.get("ocid"),
                                        reason=payload.get("reason") or "nowe dane w przypadku podobnym",
                                        actor="system:analysis_mark_affected", document_id=payload.get("document_id"))
        await s.commit()
    return {"marked": marked, "n": len(marked)}
