"""Shared plumbing for every connector/scraper (docs/scrape.md §0).

* Every fetched byte lands unchanged in data/raw/<source>/<YYYY-MM-DD>/... and gets one line in
  data/raw/<source>/manifest.jsonl (schema in scrape.md §0).
* Polite: per-host minimum interval (default 1 req/s), tenacity backoff on 429/5xx/transport
  errors, robots.txt respected, fixed User-Agent without personal data.
* Idempotent: a request whose manifest entry is fresh (same method+url+params+body, status ok,
  within TTL) is served from disk instead of the network.
* Never bypass protections: a challenge/captcha/403 page is recorded as status=blocked.

Connectors are plain synchronous functions `run(ctx, **opts) -> dict` (see ScrapeContext);
the job worker calls them in a thread.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import re
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from riskminer.config import settings

log = logging.getLogger("riskminer.connectors")

# Licence per source (scrape.md §2). Recorded on every manifest line.
LICENCES: dict[str, str] = {
    "bzp_copy": "public information (organizer copy of BZP API)",
    "bzp_api": "public information",
    "vat_whitelist": "public register",
    "teryt": "public (GUS TERYT)",
    "geo": "public (PRG GUGiK); see note for mirror licence",
    "mapa_dotacji": "public; attribution (mapadotacji.gov.pl)",
    "ted": "EU reuse (Decision 2011/833/EU)",
    "kio": "public; natural persons pseudonymised by KIO",
    "nik": "public information",
    "cru": "public (art. 34a u.f.p.)",
    "docs_22": "public information",
    "docs_sample": "public information",
    "kposk": "CC BY 4.0",
    "gus_bdl": "GUS open data, attribution",
    "gus_price_index": "GUS open data, attribution",
    "fe_projects": "public",
    "nfosigw": "CC0",
    "bip_22": "public information",
    "gus_bir": "public register",
    "krs": "public register",
    "bk2021": "public; contact persons dropped",
    "bzp_roads": "public information",
    "xlsx": "organizer dataset (HackNation 2026)",
}

BLOCK_MARKERS = re.compile(
    r"cf-chl-|challenge-platform|Just a moment\.\.\.|g-recaptcha|hcaptcha|Incapsula incident|"
    r"_Incapsula_Resource|Access denied|Attention Required! \| Cloudflare",
    re.I,
)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_name(s: str, maxlen: int = 120) -> str:
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:maxlen] or "x"


def request_key(method: str, url: str, params: Any = None, body: Any = None) -> str:
    """Stable key for idempotency: method + url + sorted params + body hash."""
    p = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
    b = body if isinstance(body, (bytes, str)) else json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    if isinstance(b, str):
        b = b.encode()
    return hashlib.sha1(f"{method.upper()} {url} {p} ".encode() + (b or b"")).hexdigest()


class Blocked(Exception):
    pass


class _RateLimiter:
    def __init__(self) -> None:
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float) -> None:
        with self._lock:
            now = time.monotonic()
            t = self._next.get(host, 0.0)
            delay = max(0.0, t - now)
            self._next[host] = max(now, t) + min_interval
        if delay:
            time.sleep(delay)


_RATE = _RateLimiter()


@dataclass
class _Robots:
    """robots.txt group for our UA (or '*'): Allow/Disallow with '*'/'$' wildcards, longest match wins
    (RFC 9309 / Google semantics), plus Crawl-delay."""
    rules: list[tuple[bool, str]] = field(default_factory=list)
    crawl_delay: float | None = None

    @classmethod
    def parse(cls, txt: str, ua_token: str = "riskminer") -> "_Robots":
        groups: list[tuple[list[str], list[tuple[bool, str]], float | None]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay: float | None = None
        last_rule = False
        for raw in (txt or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if last_rule:
                    groups.append((agents, rules, delay))
                    agents, rules, delay = [], [], None
                agents.append(v.lower())
                last_rule = False
            elif k in ("allow", "disallow"):
                last_rule = True
                if v or k == "allow":
                    rules.append((k == "allow", v))
            elif k == "crawl-delay":
                last_rule = True
                try:
                    delay = float(v)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))
        mine = [g for g in groups if any(a != "*" and a in ua_token for a in g[0])] or [g for g in groups if "*" in g[0]]
        return cls([r for g in mine for r in g[1]], max([g[2] for g in mine if g[2] is not None], default=None))

    def allows(self, url: str) -> tuple[bool, str | None]:
        parts = urllib.parse.urlsplit(url)
        path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        best: tuple[int, bool, str] | None = None
        for allow, pat in self.rules:
            rx = "^" + re.escape(pat).replace(r"\*", ".*")
            if rx.endswith(r"\$"):
                rx = rx[:-2] + "$"
            if re.match(rx, path) or re.match(rx, urllib.parse.unquote(path)):
                if best is None or len(pat) > best[0] or (len(pat) == best[0] and allow):
                    best = (len(pat), allow, pat)
        if best is None:
            return True, None
        return best[1], ("Allow: " if best[1] else "Disallow: ") + best[2]


_ROBOTS: dict[str, _Robots] = {}


@dataclass
class FetchResult:
    url: str
    status: str                # ok | empty | blocked | error
    http_status: int | None
    content: bytes | None
    path: Path | None
    sha256: str | None
    content_type: str | None
    cached: bool = False
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def text(self, encoding: str | None = None) -> str:
        if self.content is None:
            return ""
        if encoding:
            return self.content.decode(encoding, errors="replace")
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return self.content.decode("cp1250", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content or b"null")


class RawStore:
    """data/raw/<source>/ with an append-only manifest.jsonl."""

    def __init__(self, source: str, root: Path | None = None):
        self.source = source
        self.dir = (root or settings().raw_dir) / source
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir / "manifest.jsonl"
        self._index: dict[str, dict] | None = None
        self._lock = threading.Lock()

    # ---- manifest ---------------------------------------------------------------------
    def entries(self) -> list[dict]:
        if not self.manifest_path.exists():
            return []
        out = []
        with self.manifest_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return out

    def index(self) -> dict[str, dict]:
        if self._index is None:
            idx: dict[str, dict] = {}
            for e in self.entries():
                k = e.get("key")
                if k:
                    idx[k] = e   # last wins
            self._index = idx
        return self._index

    def append(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        with self._lock, self.manifest_path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(line)
            fcntl.flock(fh, fcntl.LOCK_UN)
        if self._index is not None and entry.get("key"):
            self._index[entry["key"]] = entry

    def fresh(self, key: str, ttl: timedelta | None) -> dict | None:
        e = self.index().get(key)
        if not e or e.get("status") not in ("ok", "empty") or not e.get("path"):
            return None
        if ttl is not None:
            try:
                t = datetime.strptime(e["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            except (KeyError, ValueError):
                return None
            if utcnow() - t > ttl:
                return None
        p = Path(e["path"])
        if not p.is_absolute():
            p = settings().raw_dir.parent.parent / p
        return e if p.exists() else None

    # ---- files ------------------------------------------------------------------------
    def path_for(self, rel: str, day: date | None = None) -> Path:
        day = day or utcnow().date()
        p = self.dir / day.isoformat() / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def rel(self, p: Path) -> str:
        try:
            return str(p.resolve().relative_to(settings().raw_dir.parent.parent.resolve()))
        except ValueError:
            return str(p)

    def abs(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else settings().raw_dir.parent.parent / p


@dataclass
class ScrapeContext:
    """Everything a connector needs. Create with ScrapeContext.create('ted', ...)."""

    source: str
    run_id: str
    store: RawStore
    client: httpx.Client
    min_interval: float = 1.0
    respect_robots: bool = True
    ttl: timedelta | None = None           # None = cache forever
    max_crawl_delay: float = 60.0          # hosts asking for a longer Crawl-delay are recorded as blocked
    # host (suffix) -> approval note: robots.txt is not applied to these hosts because their operator approved
    # our access; requests to them are still rate-limited (override_min_interval) and tagged in the manifest.
    robots_override: dict[str, str] = field(default_factory=dict)
    override_min_interval: float = 5.0
    licence: str = ""
    opts: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=lambda: {
        "requests": 0, "cached": 0, "ok": 0, "empty": 0, "blocked": 0, "error": 0, "records": 0})

    @classmethod
    def create(cls, source: str, run_id: str | None = None, *, min_interval: float = 1.0,
               ttl: timedelta | None = None, timeout: float = 60.0, respect_robots: bool = True,
               max_crawl_delay: float = 60.0,
               headers: dict[str, str] | None = None, verify: bool = True, **opts: Any) -> ScrapeContext:
        h = {"User-Agent": settings().user_agent, "Accept-Language": "pl,en;q=0.8"}
        h.update(headers or {})
        client = httpx.Client(headers=h, timeout=timeout, follow_redirects=True, verify=verify)
        return cls(source=source, run_id=run_id or str(uuid.uuid4()), store=RawStore(source), client=client,
                   min_interval=min_interval, respect_robots=respect_robots, ttl=ttl, max_crawl_delay=max_crawl_delay,
                   licence=LICENCES.get(source, "public"), opts=opts)

    def close(self) -> None:
        self.client.close()

    # ---- robots -----------------------------------------------------------------------
    def robots(self, url: str) -> "_Robots":
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in _ROBOTS:
            txt = ""
            try:
                r = self.client.get(origin + "/robots.txt", timeout=15)
                if r.status_code == 200 and "html" not in r.headers.get("content-type", "text/plain"):
                    txt = r.text
            except httpx.HTTPError:
                pass
            _ROBOTS[origin] = _Robots.parse(txt)
        return _ROBOTS[origin]

    def set_robots_override(self, hosts: list[str] | str, note: str, min_interval: float = 5.0) -> None:
        if isinstance(hosts, str):
            hosts = [h.strip() for h in hosts.split(",")]
        for h in hosts:
            if h:
                self.robots_override[h.lower().lstrip(".")] = note
        self.override_min_interval = max(float(min_interval), 1.0)

    def override_for(self, url: str) -> str | None:
        host = urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
        for h, note in self.robots_override.items():
            if host == h or host.endswith("." + h):
                return note
        return None

    def allowed(self, url: str) -> bool:
        return self.check_robots(url)[0]

    def check_robots(self, url: str) -> tuple[bool, str]:
        """Wildcard-aware robots.txt check (urllib.robotparser ignores '*'/'$' in paths) + Crawl-delay budget."""
        if not self.respect_robots or self.override_for(url):
            return True, ""
        rb = self.robots(url)
        ok, rule = rb.allows(url)
        if not ok:
            return False, f"robots.txt {rule}"
        if rb.crawl_delay and rb.crawl_delay > self.max_crawl_delay:
            return False, (f"robots.txt Crawl-delay {rb.crawl_delay:g}s exceeds this run's budget "
                           f"({self.max_crawl_delay:g}s); not fetched")
        return True, ""

    # ---- fetch ------------------------------------------------------------------------
    def fetch(self, url: str, *, method: str = "GET", params: dict | None = None, data: Any = None,
              json_body: Any = None, rel_path: str | None = None, ext: str | None = None,
              ttl: timedelta | None | str = "default", note: str = "", headers: dict[str, str] | None = None,
              min_interval: float | None = None, accept_status: tuple[int, ...] = (200,),
              empty_if: Any = None, check_blocked: bool = True) -> FetchResult:
        """Fetch once (or serve from the raw store), save bytes, write a manifest line.

        rel_path: file path under data/raw/<source>/<date>/ (auto from URL if omitted).
        empty_if: callable(bytes) -> bool marking a 200 response as status=empty.
        """
        body = json_body if json_body is not None else data
        key = request_key(method, url, params, body)
        use_ttl = self.ttl if ttl == "default" else ttl
        cached = self.store.fresh(key, use_ttl)  # type: ignore[arg-type]
        if cached:
            p = self.store.abs(cached["path"])
            self.stats["cached"] += 1
            return FetchResult(cached.get("final_url") or url, cached["status"], cached.get("http_status"), p.read_bytes(), p,
                               cached.get("sha256"), cached.get("content_type"), cached=True, manifest=cached)
        ok, why = self.check_robots(url)
        if not ok:
            return self.record(url, "blocked", method=method, params=params, note=why, key=key)
        host = urllib.parse.urlsplit(url).netloc
        interval = self.min_interval if min_interval is None else min_interval
        ov = self.override_for(url)
        if ov:
            interval = max(interval, self.override_min_interval)
            note = (note + " | " if note else "") + f"robots.txt override: {ov}"
        elif self.respect_robots:
            interval = max(interval, self.robots(url).crawl_delay or 0.0)
        _RATE.wait(host, interval)
        self.stats["requests"] += 1
        try:
            resp = self._send(method, url, params=params, data=data, json_body=json_body, headers=headers)
        except Exception as e:  # noqa: BLE001 - recorded in manifest
            err = f"{type(e).__name__}: {e}"[:500]
            return self.record(url, "error", method=method, params=params, note=f"{note} | {err}" if note else err, key=key)
        content = resp.content
        ctype = resp.headers.get("content-type", "")
        status = "ok"
        if resp.status_code not in accept_status:
            status = "blocked" if resp.status_code in (401, 403, 407, 451) else "error"
        if check_blocked and status == "ok" and ("html" in ctype or not ctype) and BLOCK_MARKERS.search(
                content[:20000].decode("utf-8", "replace")):
            status = "blocked"
            note = (note + " challenge/captcha page detected").strip()
        if status == "ok" and (not content or (empty_if and empty_if(content))):
            status = "empty"
        if rel_path is None:
            rel_path = self._auto_name(url, params, ext or _ext_for(ctype))
        p = self.store.path_for(rel_path)
        if p.exists() and p.read_bytes() != content:   # never overwrite: keep both
            p = p.with_name(f"{p.stem}__{key[:8]}{p.suffix}")
        p.write_bytes(content)
        digest = sha256_bytes(content)
        entry = self._entry(url, method, params, resp.status_code, ctype, len(content), digest,
                            self.store.rel(p), status, note, key, body)
        if str(resp.url) != url:
            entry["final_url"] = str(resp.url)
        self.store.append(entry)
        self.stats[status] = self.stats.get(status, 0) + 1
        return FetchResult(str(resp.url), status, resp.status_code, content, p, digest, ctype, manifest=entry)

    @retry(reraise=True, stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=90),
           retry=retry_if_exception(lambda e: isinstance(e, (httpx.TransportError, _Retryable))))
    def _send(self, method: str, url: str, *, params=None, data=None, json_body=None, headers=None) -> httpx.Response:
        r = self.client.request(method, url, params=params, data=data, json=json_body, headers=headers)
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("retry-after")
            if ra and ra.isdigit():
                time.sleep(min(int(ra), 120))
            raise _Retryable(f"HTTP {r.status_code}")
        return r

    def record(self, url: str, status: str, *, method: str = "GET", params: dict | None = None, note: str = "",
               key: str | None = None, http_status: int | None = None, path: str | None = None,
               extra: dict | None = None) -> FetchResult:
        """Manifest line without (or with an externally written) payload: blocked/error/empty/search records."""
        key = key or request_key(method, url, params, None)
        entry = self._entry(url, method, params, http_status, None, None, None, path, status, note, key, None)
        if extra:
            entry.update(extra)
        self.store.append(entry)
        self.stats[status] = self.stats.get(status, 0) + 1
        return FetchResult(url, status, http_status, None, None, None, None, manifest=entry)

    def save_derived(self, rel_path: str, content: bytes, *, url: str, note: str = "", status: str = "ok",
                     extra: dict | None = None) -> FetchResult:
        """Store bytes produced locally from a raw file (e.g. pdftotext output) with a manifest line.
        Idempotent: identical bytes for the same rel_path are not written or logged again."""
        dkey = request_key("DERIVED", url, {"p": rel_path})
        prev = self.store.fresh(dkey, None)
        if prev and prev.get("sha256") == sha256_bytes(content):
            pp = self.store.abs(prev["path"])
            return FetchResult(url, prev["status"], None, content, pp, prev["sha256"], prev.get("content_type"),
                               cached=True, manifest=prev)
        p = self.store.path_for(rel_path)
        p.write_bytes(content)
        digest = sha256_bytes(content)
        entry = self._entry(url, "DERIVED", None, None, _ctype_for(p.suffix), len(content), digest,
                            self.store.rel(p), status, note, request_key("DERIVED", url, {"p": rel_path}), None)
        if extra:
            entry.update(extra)
        self.store.append(entry)
        return FetchResult(url, status, None, content, p, digest, entry["content_type"], manifest=entry)

    def _entry(self, url, method, params, http_status, ctype, nbytes, digest, path, status, note, key, body) -> dict:
        e = {
            "source": self.source, "fetched_at": _iso(utcnow()), "method": method, "url": url,
            "params": params or {}, "http_status": http_status, "content_type": ctype, "bytes": nbytes,
            "sha256": digest, "path": path, "licence": self.licence, "run_id": self.run_id,
            "status": status, "note": note, "key": key,
        }
        if body is not None and method.upper() == "POST":
            e["body"] = body if isinstance(body, (dict, list)) else str(body)[:2000]
        return e

    def _auto_name(self, url: str, params: dict | None, ext: str) -> str:
        parts = urllib.parse.urlsplit(url)
        stem = safe_name(parts.path.strip("/").replace("/", "_") or parts.netloc, 80)
        if params or parts.query:
            stem += "__" + hashlib.sha1(json.dumps([parts.query, params], sort_keys=True, default=str).encode()).hexdigest()[:10]
        return f"{stem}{ext}"


class _Retryable(Exception):
    pass


def _ext_for(ctype: str) -> str:
    c = (ctype or "").lower()
    for k, v in (("json", ".json"), ("html", ".html"), ("xml", ".xml"), ("pdf", ".pdf"), ("csv", ".csv"),
                 ("zip", ".zip"), ("spreadsheetml", ".xlsx"), ("ms-excel", ".xls"), ("wordprocessingml", ".docx"),
                 ("msword", ".doc"), ("text/plain", ".txt"), ("geo+json", ".geojson")):
        if k in c:
            return v
    return ".bin"


def _ctype_for(suffix: str) -> str:
    return {".txt": "text/plain", ".json": "application/json", ".csv": "text/csv",
            ".geojson": "application/geo+json", ".html": "text/html"}.get(suffix.lower(), "application/octet-stream")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
