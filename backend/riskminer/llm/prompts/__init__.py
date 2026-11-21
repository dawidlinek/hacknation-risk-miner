"""Versioned Polish prompts: `<name>.md` with YAML front matter (version, alias, output). Variables use $name."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

import yaml

DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str
    meta: dict

    @property
    def ref(self) -> str:
        """`<name>@v<version>+<sha256[:8]>`: joins quality numbers to the exact prompt text."""
        return f"{self.name}@v{self.version}+{hashlib.sha256(self.text.encode()).hexdigest()[:8]}"

    def render(self, **vars) -> str:
        return Template(self.text).safe_substitute(**vars)


@lru_cache
def load(name: str) -> Prompt:
    raw = (DIR / f"{name}.md").read_text(encoding="utf-8")
    meta: dict = {}
    body = raw
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    return Prompt(name=name, version=str(meta.get("version", 1)), text=body.strip(), meta=meta)
