"""Block-based layout shared by the record export and the analysis pack.

A document is a list of blocks collected by `Blocks` (headings, paragraphs, bullet lists, tables, callouts, key-number tiles,
the provenance legend, page breaks). The same blocks render to DOCX (python-docx, MIT) and to Markdown; the PDF is the DOCX
through LibreOffice (`documents/convert.py`, MPL-2.0 as a separate binary). Fonts: Liberation Sans / Mono (OFL), installed in
the backend image, so Polish diacritics are embedded and the PDF text is selectable.

Text segments: a cell or paragraph value is a str or a list of segments; a segment is a str or a dict
{"t": text, "b": bold, "i": italic, "c": "RRGGBB", "s": size_pt, "mono": bool, "link": url}. `tag(key)` makes a provenance tag.
Layout rules: brand blue #3056F5 for headings and accents, yellow #FFD23F only for "wymaga uwagi" (tone="attention"),
no em dash (U+2014) and no middle dot (U+00B7) anywhere (`clean` turns them into an en dash / comma).
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BLUE, YELLOW, INK, MUTED, LINE = "3056F5", "FFD23F", "1B1F2A", "5B6475", "D5DAE5"
BAND, TINT, TINT_Y, GREEN, AMBER, WHITE = "F4F6FB", "EDF1FE", "FFF4CC", "1E7B4F", "8A5A00", "FFFFFF"
FONT, MONO = "Liberation Sans", "Liberation Mono"
APP_URL = "https://exante.linek.dev"
TZ = ZoneInfo("Europe/Warsaw")
PAGE_W_CM = 17.4                                       # A4 (21 cm) minus 2 x 1.8 cm margins
BANNED = ("\u2014", "\u00b7")

TAGS = {"src": ("ŹRÓDŁO", INK), "calc": ("OBLICZENIE", BLUE), "ai": ("PROPOZYCJA AI", AMBER),
        "pending": ("DO ZATWIERDZENIA", AMBER), "approved": ("ZATWIERDZONE", GREEN), "assumption": ("ZAŁOŻENIE EKSPERTA", MUTED),
        "rejected": ("ODRZUCONE", MUTED)}
TAG_HELP = {
    "src": "fakt przepisany ze źródła: ogłoszenie BZP (numer i pole) albo dokument (strona); cytaty są dosłowne.",
    "calc": "wynik reguły albo statystyki na danych źródłowych; podajemy liczbę przypadków n i metodę.",
    "ai": "odczyt modelu językowego, niezatwierdzony przez eksperta; nie wchodzi do statystyk ani wniosków.",
    "pending": "fakt wyczytany regułą z nowego dokumentu, czeka na decyzję eksperta.",
    "approved": "pozycja sprawdzona i zatwierdzona (albo poprawiona) przez eksperta; AI jej nie nadpisze.",
    "assumption": "parametr z Katalogu ryzyk ustalony przez eksperta (np. termin programu, wpływ działania).",
}


# ------------------------------------------------------------------------------------------------------------ format

def clean(s: Any) -> str:
    """Our copy never carries an em dash or a middle dot; quotes keep their words, the dash becomes an en dash.
    Private-use characters (symbol-font bullets from PDF text) would render as boxes, so they become a bullet."""
    t = "" if s is None else str(s)
    t = t.replace("\u2014", "\u2013").replace("\u00b7", ",")
    if any("\ue000" <= ch <= "\uf8ff" for ch in t):
        t = "".join("\u2022" if "\ue000" <= ch <= "\uf8ff" else ch for ch in t)
    return t


def fmt_num(x: float | None, decimals: int = 0) -> str:
    if x is None:
        return ""
    s = f"{float(x):,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",")


def fmt_date(v: Any) -> str:
    if not v:
        return ""
    if isinstance(v, datetime):
        return v.astimezone(TZ).strftime("%d.%m.%Y") if v.tzinfo else v.strftime("%d.%m.%Y")
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    s = str(v)
    try:
        if "T" in s and len(s) > 10:
            return datetime.fromisoformat(s).astimezone(TZ).strftime("%d.%m.%Y")
        return date.fromisoformat(s[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return s[:10]


def fmt_dt(v: datetime) -> str:
    return v.astimezone(TZ).strftime("%d.%m.%Y, %H:%M")


def money_pl(m: dict | None, empty: str = "brak") -> str:
    """{'amount': '49903.54', 'currency': 'PLN', 'vat_basis': 'gross'} -> '49 903,54 zł brutto' (unknown basis is said so)."""
    if not m or m.get("amount") in (None, ""):
        return empty
    try:
        amt = fmt_num(float(m["amount"]), 2)
    except (TypeError, ValueError):
        return f"{m.get('amount')} {m.get('currency') or ''}".strip()
    cur = "zł" if (m.get("currency") or "PLN") == "PLN" else m.get("currency")
    vat = {"gross": "brutto", "net": "netto"}.get(m.get("vat_basis") or "", "(podstawa VAT nieznana)")
    return f"{amt} {cur} {vat}"


def mln(amount: Any, decimals: int = 2) -> str:
    try:
        return f"{fmt_num(float(amount) / 1e6, decimals)} mln zł"
    except (TypeError, ValueError):
        return ""


def pct(x: float | None, decimals: int = 0) -> str:
    """Share 0..1 -> '34%'."""
    return "" if x is None else f"{fmt_num(float(x) * 100, decimals)}%"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Polish plural: 1 zdarzenie, 2 zdarzenia, 5 zdarzeń (with the number)."""
    n = int(n)
    if n == 1:
        return f"1 {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def plain(value: Any) -> str:
    """Segments -> plain text (Markdown cells, tests)."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return clean(value)
    if isinstance(value, dict):
        value = [value]
    out = []
    for seg in value:
        if isinstance(seg, str):
            out.append(clean(seg))
        elif seg.get("tag"):
            out.append(f"[{clean(seg['t'])}]")
        else:
            out.append(clean(seg.get("t", "")))
    return "".join(out)


def tag(key: str) -> dict:
    label, color = TAGS[key]
    return {"t": label, "c": color, "b": True, "s": 6.5, "tag": True}


def prov_key(origin: str | None, status: str | None, assumption: bool = False) -> str:
    if status in ("approved", "edited"):
        return "approved"
    if status == "rejected":
        return "rejected"
    if assumption:
        return "assumption"
    if origin == "AI":
        return "ai"
    if status == "proposed":
        return "pending"
    return "calc" if origin == "CALC" else "src"


def tagged(key: str, *rest: Any) -> list:
    """[TAG] followed by text segments."""
    segs: list = [tag(key), " "]
    for r in rest:
        if isinstance(r, list):
            segs.extend(r)
        elif r is not None:
            segs.append(r)
    return segs


# ------------------------------------------------------------------------------------------------------------- blocks

class Blocks:
    """Collects layout blocks; `to_docx` / `to_markdown` render them."""

    def __init__(self, *, doc_title: str, doc_id: str, generated_at: datetime | None = None, subject: str = ""):
        self.doc_title, self.doc_id, self.subject = doc_title, doc_id, subject
        self.now = (generated_at or datetime.now(TZ)).astimezone(TZ)
        self.items: list[tuple] = []

    def title(self, kicker: str, title: str, lines: list[Any] | None = None):
        self.items.append(("title", kicker, title, lines or []))

    def h1(self, text: str):
        self.items.append(("h1", text))

    def h2(self, text: str):
        self.items.append(("h2", text))

    def p(self, value: Any, **kw):
        if value:
            self.items.append(("p", value, kw))

    def note(self, value: Any):
        if value:
            self.items.append(("note", value))

    def bullets(self, items: list[Any]):
        items = [i for i in items if i]
        if items:
            self.items.append(("bullets", items))

    def table(self, header: list[str], rows: list[list[Any]], widths: list[float], **kw):
        self.items.append(("table", header, rows, widths, kw))

    def kv(self, rows: list[list[Any]], widths: tuple[float, float] = (4.6, PAGE_W_CM - 4.6)):
        self.items.append(("kv", rows, widths))

    def callout(self, body: Any, *, tone: str = "info", title: str | None = None):
        self.items.append(("callout", body, tone, title))

    def tiles(self, items: list[dict]):
        self.items.append(("tiles", items))

    def legend(self, keys: list[str]):
        self.items.append(("legend", keys))

    def page_break(self):
        self.items.append(("pagebreak",))

    # ------------------------------------------------------------------------------------------------ markdown

    def to_markdown(self) -> str:
        L: list[str] = []
        for b in self.items:
            k = b[0]
            if k == "title":
                L += [f"# {clean(b[2])}", "", f"_{clean(b[1])}, {clean(self.doc_id)}_", ""]
                L += [plain(x) + "  " for x in b[3]] + [""]
            elif k == "h1":
                L += [f"## {clean(b[1])}", ""]
            elif k == "h2":
                L += [f"### {clean(b[1])}", ""]
            elif k == "p":
                L += [plain(b[1]), ""]
            elif k == "note":
                L += [f"_{plain(b[1])}_", ""]
            elif k == "bullets":
                L += [f"- {plain(x)}" for x in b[1]] + [""]
            elif k in ("table", "kv"):
                header, rows = (b[1], b[2]) if k == "table" else (["Pole", "Wartość"], b[1])
                cell = lambda v: plain(v).replace("|", "/").replace("\n", " ")
                L.append("| " + " | ".join(cell(h) for h in header) + " |")
                L.append("|" + "---|" * len(header))
                L += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
                L.append("")
            elif k == "callout":
                L += [f"> **{clean(b[3])}**" if b[3] else ">", f"> {plain(b[1])}", ""]
            elif k == "tiles":
                L += [f"- **{plain(t.get('value'))}** {plain(t.get('label'))} ({plain(t.get('foot'))})" for t in b[1]] + [""]
            elif k == "legend":
                L += ["Oznaczenia pochodzenia: " + "; ".join(f"[{TAGS[x][0]}] {TAG_HELP[x]}" for x in b[1]), ""]
        L += ["---", f"ex ante, {APP_URL}, wygenerowano {fmt_dt(self.now)}", ""]
        return "\n".join(L)

    # ----------------------------------------------------------------------------------------------------- docx

    def to_docx(self) -> bytes:
        w = _Docx(self)
        for b in self.items:
            getattr(w, "b_" + b[0])(*b[1:])
        buf = io.BytesIO()
        w.doc.save(buf)
        return buf.getvalue()


# ---------------------------------------------------------------------------------------------------------- docx impl

def _set_fonts(el_rpr, name: str):
    rf = el_rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        el_rpr.insert(0, rf)
    for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rf.get(qn(a)) is not None:
            del rf.attrib[qn(a)]
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), name)


def _style(st, *, size=None, bold=None, color=None, italic=None, name=FONT, before=None, after=None, keep_next=None):
    f = st.font
    f.name = name
    _set_fonts(st.element.get_or_add_rPr(), name)
    if size is not None:
        f.size = Pt(size)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    if color:
        f.color.rgb = RGBColor.from_string(color)
    pf = st.paragraph_format
    if before is not None:
        pf.space_before = Pt(before)
    if after is not None:
        pf.space_after = Pt(after)
    if keep_next is not None:
        pf.keep_with_next = keep_next
    ppr = st.element.pPr
    if ppr is not None:
        for bd in ppr.findall(qn("w:pBdr")):
            ppr.remove(bd)


def _shade(cell, fill: str):
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:shd")):
        tcPr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _cell_border(cell, edge: str, color: str, sz: int):
    tcPr = cell._tc.get_or_add_tcPr()
    b = tcPr.find(qn("w:tcBorders"))
    if b is None:
        b = OxmlElement("w:tcBorders")
        tcPr.append(b)
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:color"), color)
    b.append(el)


def _para_border(p, edge: str, color: str = LINE, sz: int = 6):
    ppr = p._p.get_or_add_pPr()
    bd = ppr.find(qn("w:pBdr"))
    if bd is None:
        bd = OxmlElement("w:pBdr")
        ppr.append(bd)
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:space"), "4")
    el.set(qn("w:color"), color)
    bd.append(el)


def _field(p, instr: str, size: float, color: str):
    def run():
        r = p.add_run()
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor.from_string(color)
        return r
    r1 = run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "begin")
    r1._r.append(fc)
    r2 = run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = f" {instr} "
    r2._r.append(it)
    r3 = run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "separate")
    r3._r.append(fc)
    run().text = "1"
    r5 = run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "end")
    r5._r.append(fc)


def _hyperlink(p, url: str, text: str, size: float | None, color: str = BLUE, bold: bool = False):
    r_id = p.part.relate_to(url, RT.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), r_id)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    c = OxmlElement("w:color")
    c.set(qn("w:val"), color)
    rpr.append(c)
    if bold:
        rpr.append(OxmlElement("w:b"))
    if size:
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(round(size * 2)))
        rpr.append(sz)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = clean(text)
    r.append(t)
    h.append(r)
    p._p.append(h)


class _Docx:
    def __init__(self, b: Blocks):
        self.b = b
        self.doc = Document()
        sec = self.doc.sections[0]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(1.8)
        sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(1.9)
        sec.header_distance, sec.footer_distance = Cm(0.9), Cm(0.8)
        st = self.doc.styles
        _style(st["Normal"], size=9.5, color=INK, after=3)
        st["Normal"].paragraph_format.line_spacing = 1.12
        _style(st["Title"], size=19, bold=True, color=INK, after=2)
        _style(st["Heading 1"], size=13.5, bold=True, color=BLUE, before=13, after=5, keep_next=True)
        _style(st["Heading 2"], size=10.5, bold=True, color=INK, before=9, after=3, keep_next=True)
        _style(st["List Bullet"], size=9.5, color=INK, after=2)
        for s in ("Heading 1", "Heading 2", "Title"):
            st[s].font.italic = False
        cp = self.doc.core_properties
        cp.title = f"{b.doc_title} {b.doc_id}"
        cp.author = "ex ante"
        cp.subject = b.subject or b.doc_title
        cp.keywords = "ex ante; wod-kan; ryzyko; MFiPR"
        cp.comments = APP_URL
        self._header_footer()

    # ---------------------------------------------------------------------------------------------- page frame

    def _header_footer(self):
        sec = self.doc.sections[0]
        hp = sec.header.paragraphs[0]
        hp.paragraph_format.tab_stops.add_tab_stop(Cm(PAGE_W_CM), WD_TAB_ALIGNMENT.RIGHT)
        r = hp.add_run("ex ante")
        r.bold, r.font.size, r.font.color.rgb = True, Pt(12), RGBColor.from_string(BLUE)
        r = hp.add_run(f"\t{clean(self.b.doc_title)}  |  {clean(self.b.doc_id)}")
        r.font.size, r.font.color.rgb = Pt(8), RGBColor.from_string(MUTED)
        _para_border(hp, "bottom")
        fp = sec.footer.paragraphs[0]
        fp.paragraph_format.tab_stops.add_tab_stop(Cm(PAGE_W_CM / 2), WD_TAB_ALIGNMENT.CENTER)
        fp.paragraph_format.tab_stops.add_tab_stop(Cm(PAGE_W_CM), WD_TAB_ALIGNMENT.RIGHT)
        _para_border(fp, "top")
        r = fp.add_run(f"Wygenerowano {fmt_dt(self.b.now)}\t")
        r.font.size, r.font.color.rgb = Pt(7.5), RGBColor.from_string(MUTED)
        _hyperlink(fp, APP_URL, APP_URL, 7.5)
        r = fp.add_run("\tStrona ")
        r.font.size, r.font.color.rgb = Pt(7.5), RGBColor.from_string(MUTED)
        _field(fp, "PAGE", 7.5, MUTED)
        r = fp.add_run(" z ")
        r.font.size, r.font.color.rgb = Pt(7.5), RGBColor.from_string(MUTED)
        _field(fp, "NUMPAGES", 7.5, MUTED)

    # ----------------------------------------------------------------------------------------------- text runs

    def runs(self, p, value: Any, *, size: float | None = None, color: str | None = None, bold: bool = False,
             italic: bool = False):
        if value is None:
            return
        if isinstance(value, (str, int, float)):
            value = [str(value)]
        elif isinstance(value, dict):
            value = [value]
        for seg in value:
            if isinstance(seg, str):
                seg = {"t": seg}
            t = clean(seg.get("t", ""))
            if not t:
                continue
            s = seg.get("s", size)
            if seg.get("link"):
                _hyperlink(p, seg["link"], t, s, bold=seg.get("b", False))
                continue
            for i, part in enumerate(t.split("\n")):
                if i:
                    p.add_run().add_break(WD_BREAK.LINE)
                if not part:
                    continue
                r = p.add_run(part)
                if s:
                    r.font.size = Pt(s)
                c = seg.get("c", color)
                if c:
                    r.font.color.rgb = RGBColor.from_string(c)
                if seg.get("b", bold):
                    r.bold = True
                if seg.get("i", italic):
                    r.italic = True
                if seg.get("mono"):
                    r.font.name = MONO
                    _set_fonts(r._r.get_or_add_rPr(), MONO)

    def _para(self, value: Any = None, *, style: str | None = None, size=None, color=None, bold=False, italic=False,
              after: float | None = None, before: float | None = None, align=None, keep_next=False):
        p = self.doc.add_paragraph(style=style)
        self.runs(p, value, size=size, color=color, bold=bold, italic=italic)
        pf = p.paragraph_format
        if after is not None:
            pf.space_after = Pt(after)
        if before is not None:
            pf.space_before = Pt(before)
        if align:
            p.alignment = align
        if keep_next:
            pf.keep_with_next = True
        return p

    # ------------------------------------------------------------------------------------------------- tables

    def _table(self, nrows: int, widths: list[float], *, borders: bool = True, inside_v: bool = False):
        total = sum(widths)
        widths = [w * PAGE_W_CM / total for w in widths] if abs(total - PAGE_W_CM) > 0.05 else widths
        t = self.doc.add_table(rows=nrows, cols=len(widths))
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
        t.autofit = False
        tblPr = t._tbl.tblPr
        lay = OxmlElement("w:tblLayout")
        lay.set(qn("w:type"), "fixed")
        tblPr.append(lay)
        tw = OxmlElement("w:tblW")
        tw.set(qn("w:w"), str(int(PAGE_W_CM * 567)))
        tw.set(qn("w:type"), "dxa")
        for old in tblPr.findall(qn("w:tblW")):
            tblPr.remove(old)
        tblPr.append(tw)
        mar = OxmlElement("w:tblCellMar")
        for edge, v in (("top", 40), ("bottom", 40), ("left", 85), ("right", 85)):
            e = OxmlElement(f"w:{edge}")
            e.set(qn("w:w"), str(v))
            e.set(qn("w:type"), "dxa")
            mar.append(e)
        tblPr.append(mar)
        bd = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement(f"w:{edge}")
            on = borders and (edge in ("top", "bottom", "insideH") or (inside_v and edge == "insideV"))
            e.set(qn("w:val"), "single" if on else "nil")
            if on:
                e.set(qn("w:sz"), "4")
                e.set(qn("w:color"), LINE)
            bd.append(e)
        tblPr.append(bd)
        grid = t._tbl.tblGrid
        for gc, wcm in zip(grid.findall(qn("w:gridCol")), widths, strict=False):
            gc.set(qn("w:w"), str(int(wcm * 567)))
        for row in t.rows:
            for c, wcm in zip(row.cells, widths, strict=False):
                c.width = Cm(wcm)
        return t

    def _cell(self, cell, value: Any, *, size: float, color: str | None = None, bold: bool = False, align=None):
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.line_spacing = 1.05
        if align:
            p.alignment = align
        self.runs(p, value, size=size, color=color, bold=bold)

    @staticmethod
    def _row_flags(row, *, header: bool = False, cant_split: bool = True):
        trPr = row._tr.get_or_add_trPr()
        if header:
            e = OxmlElement("w:tblHeader")
            e.set(qn("w:val"), "true")
            trPr.append(e)
        if cant_split:
            e = OxmlElement("w:cantSplit")
            e.set(qn("w:val"), "true")
            trPr.append(e)

    def _spacer(self, pt: float = 4):
        p = self.doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        r = p.add_run("")
        r.font.size = Pt(pt)
        p.paragraph_format.line_spacing = Pt(pt)

    # ------------------------------------------------------------------------------------------------- blocks

    def b_title(self, kicker: str, title: str, lines: list):
        self._para(kicker.upper(), size=8.5, color=BLUE, bold=True, after=2)
        p = self.doc.add_paragraph(style="Title")
        self.runs(p, title)
        for ln in lines:
            self._para(ln, size=9, color=MUTED, after=1)
        self._spacer(6)

    def b_h1(self, text: str):
        self.doc.add_heading(clean(text), 1)

    def b_h2(self, text: str):
        self.doc.add_heading(clean(text), 2)

    def b_p(self, value: Any, kw: dict):
        self._para(value, size=kw.get("size"), color=kw.get("color"), bold=kw.get("bold", False), italic=kw.get("italic", False),
                   after=kw.get("after"), keep_next=kw.get("keep_next", False))

    def b_note(self, value: Any):
        self._para(value, size=8, color=MUTED, italic=True, after=4)

    def b_bullets(self, items: list):
        # a typed bullet (not Word list numbering): the PDF text layer then has a real U+2022, not a symbol-font glyph
        for it in items:
            p = self.doc.add_paragraph()
            pf = p.paragraph_format
            pf.left_indent, pf.first_line_indent, pf.space_after = Cm(0.5), Cm(-0.4), Pt(2.5)
            pf.tab_stops.add_tab_stop(Cm(0.5))
            r = p.add_run("\u2022\t")
            r.font.color.rgb = RGBColor.from_string(BLUE)
            self.runs(p, it)

    def b_table(self, header: list[str], rows: list[list[Any]], widths: list[float], kw: dict):
        size = kw.get("size", 8)
        zebra = kw.get("zebra", True)
        t = self._table(1 + len(rows), widths, inside_v=kw.get("inside_v", False))
        hdr = t.rows[0]
        self._row_flags(hdr, header=True)
        for c, h in zip(hdr.cells, header, strict=False):
            _shade(c, kw.get("header_fill", BLUE))
            self._cell(c, h, size=size, color=WHITE, bold=True)
        right = set(kw.get("right", ()))
        shade_rows = kw.get("shade_rows") or {}
        for i, row in enumerate(rows):
            tr = t.rows[i + 1]
            text_len = sum(len(plain(v)) for v in row)
            self._row_flags(tr, cant_split=text_len < 700)
            fill = shade_rows.get(i) or (BAND if zebra and i % 2 == 1 else None)
            for j, (c, v) in enumerate(zip(tr.cells, row, strict=False)):
                if fill:
                    _shade(c, fill)
                self._cell(c, v, size=size, bold=kw.get("first_bold", False) and j == 0,
                           align=WD_ALIGN_PARAGRAPH.RIGHT if j in right else None)
        self._spacer()

    def b_kv(self, rows: list[list[Any]], widths: tuple[float, float]):
        t = self._table(len(rows), list(widths))
        for i, (k, v) in enumerate(rows):
            tr = t.rows[i]
            self._row_flags(tr)
            self._cell(tr.cells[0], k, size=8.5, color=MUTED, bold=True)
            self._cell(tr.cells[1], v, size=8.5)
        self._spacer()

    def b_callout(self, body: Any, tone: str, title: str | None):
        t = self._table(1, [PAGE_W_CM], borders=False)
        c = t.rows[0].cells[0]
        self._row_flags(t.rows[0])
        _shade(c, TINT_Y if tone == "attention" else TINT if tone == "info" else BAND)
        _cell_border(c, "left", YELLOW if tone == "attention" else BLUE if tone == "info" else LINE, 24)
        p = c.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        if title:
            self.runs(p, title, size=9.5, bold=True, color=INK)
            p = c.add_paragraph()
            p.paragraph_format.space_after = Pt(1)
        if isinstance(body, list) and body and isinstance(body[0], list):        # several paragraphs
            for i, para in enumerate(body):
                q = p if i == 0 else c.add_paragraph()
                q.paragraph_format.space_after = Pt(2)
                self.runs(q, para, size=8.8)
        else:
            self.runs(p, body, size=8.8)
        self._spacer(6)

    def b_tiles(self, items: list[dict]):
        n = len(items)
        t = self._table(1, [PAGE_W_CM / n] * n, borders=False)
        self._row_flags(t.rows[0])
        for c, it in zip(t.rows[0].cells, items, strict=False):
            att = it.get("tone") == "attention"
            _shade(c, TINT_Y if att else TINT)
            _cell_border(c, "top", YELLOW if att else BLUE, 18)
            _cell_border(c, "right", WHITE, 24)
            p = c.paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            self.runs(p, it.get("value"), size=15, bold=True, color=INK if att else BLUE)
            q = c.add_paragraph()
            q.paragraph_format.space_after = Pt(1)
            self.runs(q, it.get("label"), size=8.2, bold=True, color=INK)
            if it.get("foot"):
                r = c.add_paragraph()
                r.paragraph_format.space_after = Pt(1)
                self.runs(r, it.get("foot"), size=7.2, color=MUTED)
        self._spacer(6)

    def b_legend(self, keys: list[str]):
        t = self._table(len(keys) + 1, [3.4, PAGE_W_CM - 3.4], borders=False)
        c0 = t.rows[0].cells[0].merge(t.rows[0].cells[1])
        self._cell(c0, "Jak czytać oznaczenia pochodzenia", size=8.5, bold=True, color=INK)
        for i, k in enumerate(keys, 1):
            tr = t.rows[i]
            self._row_flags(tr)
            self._cell(tr.cells[0], [tag(k)], size=7)
            self._cell(tr.cells[1], TAG_HELP[k], size=8, color=INK)
        for row in t.rows:
            for c in row.cells:
                _shade(c, BAND)
        self._spacer(6)

    def b_pagebreak(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
