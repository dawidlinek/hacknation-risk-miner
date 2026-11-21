"""Backend protocol and the request parts every backend understands."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Text:
    text: str


@dataclass
class PageText:
    doc_id: int | str
    page: int
    text: str


@dataclass
class PdfFile:
    """Gemini PDF input (public scans without a text layer only; refused for confidential input)."""
    doc_id: int | str
    path: str


@dataclass
class Json:
    obj: Any
    tag: str = "dane"


Part = Text | PageText | PdfFile | Json


def render_text(parts: list[Part]) -> str:
    """Text rendering used by text-only backends and by the request hash."""
    out = []
    for p in parts:
        if isinstance(p, Text):
            out.append(p.text)
        elif isinstance(p, PageText):
            out.append(f'<page n="{p.page}" doc="{p.doc_id}">\n{p.text}\n</page>')
        elif isinstance(p, Json):
            out.append(f"<{p.tag}>\n{json.dumps(p.obj, ensure_ascii=False, default=str)}\n</{p.tag}>")
        elif isinstance(p, PdfFile):
            out.append(f'<pdf doc="{p.doc_id}"/>')
    return "\n".join(out)


@dataclass
class GenParams:
    model: str
    system: str
    parts: list[Part]
    schema: dict | None = None
    max_output_tokens: int = 4096
    temperature: float | None = None
    params: dict[str, Any] = field(default_factory=dict)      # llm.model_params[model]
    timeout_s: float = 60
    cached_content: str | None = None


@dataclass
class RawResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    tokens_thought: int = 0
    finish_reason: str | None = None
    raw: dict | None = None
    replayed: bool = False
    cost_usd: float | None = None      # provider-reported cost (OpenRouter usage.cost) overrides the price table


class Backend(Protocol):
    kind: str

    async def generate(self, p: GenParams) -> RawResult: ...

    async def health(self) -> dict: ...
