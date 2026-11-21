"""Recorded responses (cassettes) for CI and the demo fallback (docs/impl/verification.md §2.5).

`tests/fixtures/llm/<task>/<request_hash>.json` = {"task", "provider", "model", "prompt_version", "text", "tokens_in",
"tokens_out", ...}. RISKMINER_LLM_FAKE=1 forces replay (strict: a miss raises ReplayMiss); RISKMINER_LLM_RECORD=1 writes
a cassette after each real call. A cassette whose hash is unknown can still be found by `match` (task + a substring of
the rendered prompt), which keeps hand-written negative cassettes small."""
from __future__ import annotations

import json
from pathlib import Path

from riskminer.llm.backends.base import RawResult
from riskminer.llm.config import replay_dir
from riskminer.llm.errors import ReplayMiss


def cassette_path(task: str, request_hash: str) -> Path:
    return Path(replay_dir()) / task / f"{request_hash}.json"


def load(task: str, request_hash: str, rendered: str = "") -> RawResult:
    p = cassette_path(task, request_hash)
    d = None
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
    else:
        tdir = Path(replay_dir()) / task
        if tdir.is_dir():
            for f in sorted(tdir.glob("*.json")):
                try:
                    c = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                m = c.get("match")
                if m and m in rendered:
                    d = c
                    break
    if d is None:
        raise ReplayMiss(f"no cassette for {task}/{request_hash}")
    return RawResult(text=d["text"] if isinstance(d["text"], str) else json.dumps(d["text"], ensure_ascii=False),
                     tokens_in=d.get("tokens_in", 0), tokens_out=d.get("tokens_out", 0),
                     tokens_cached=d.get("tokens_cached", 0), tokens_thought=d.get("tokens_thought", 0),
                     finish_reason=d.get("finish_reason"), replayed=True)


def save(task: str, request_hash: str, meta: dict, res: RawResult) -> Path:
    p = cassette_path(task, request_hash)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**meta, "text": res.text, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                             "tokens_cached": res.tokens_cached, "tokens_thought": res.tokens_thought,
                             "finish_reason": res.finish_reason}, ensure_ascii=False, indent=1), encoding="utf-8")
    return p
