#!/usr/bin/env python3
"""Build a VU DXCC standings PDF from ARRL DXCC Standings downloads.

Usage:
    python3 vudxcc.py                          # uses today's date, PDF in CWD
    python3 vudxcc.py --date 20260422          # specific snapshot date
    python3 vudxcc.py --output out.pdf         # custom output path
    python3 vudxcc.py --json data.json         # also emit machine-readable JSON
    python3 vudxcc.py --previous prev.json     # diff against a prior snapshot
                                               #   (changed cells highlighted in PDF/JSON)
    python3 vudxcc.py --no-cache               # force re-download
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

import pdfplumber
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ARRL_BASE = "https://www.arrl.org/system/dxcc/view"

# (column_key, ARRL URL token, display label, parser type)
#   band: multi-column count-then-callsigns layout (most DXCC PDFs)
#   hr  : Honor Roll single-column "CALL/COUNT" layout
CATEGORIES: list[tuple[str, str, str, str]] = [
    ("Mix",  "MIXED",     "Mix",  "band"),
    ("Ph",   "PHONE",     "Ph",   "band"),
    ("CW",   "CW",        "CW",   "band"),
    ("Dig",  "RTTY",      "Dig",  "band"),
    ("Sat",  "SATELLITE", "Sat",  "band"),
    ("160",  "160M",      "160",  "band"),
    ("80",   "80M",       "80",   "band"),
    ("40",   "40M",       "40",   "band"),
    ("30",   "30M",       "30",   "band"),
    ("20",   "20M",       "20",   "band"),
    ("17",   "17M",       "17",   "band"),
    ("15",   "15M",       "15",   "band"),
    ("12",   "12M",       "12",   "band"),
    ("10",   "10M",       "10",   "band"),
    ("6",    "6M",        "6",    "band"),
    ("Chal", "CHAL",      "Chal", "band"),
    ("Hon",  "HR",        "Hon",  "hr"),
]
BAND_MODE_KEYS = [k for k, _, _, _ in CATEGORIES if k not in ("Chal", "Hon")]
# Any VU-prefixed callsign: VU + one-or-more digits + one-or-more letters,
# with optional leading/trailing endorsement-pending marker (*). This covers
# standard VU2/VU3/VU4/VU7 calls as well as special-event series like
# VU24xxx, VU75xxx, VU50xxx that India issues from time to time.
VU_RE = re.compile(r"^\*?VU\d+[A-Z]+\*?$")


def _clean_call(token: str) -> str:
    """Strip leading/trailing endorsement-pending markers from a callsign token."""
    return token.strip("*")


# ---------- network ----------

def url_for(token: str, date_str: str) -> str:
    return f"{ARRL_BASE}/DXCC-{token}-{date_str}-USLetter.pdf"


def download_pdf(url: str, dest: Path, use_cache: bool = True) -> bytes:
    if use_cache and dest.exists() and dest.stat().st_size > 1024:
        return dest.read_bytes()
    req = Request(url, headers={"User-Agent": "vudxcc-tool/1.0"})
    with urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


# ---------- parsing ----------

def cluster_columns(words, n_cols: int = 6, tol: int = 20):
    """Assign word items to N columns by clustering x0. Returns list of lists sorted top-to-bottom."""
    if not words:
        return []
    x_counts = Counter(round(w["x0"]) for w in words)
    candidates = [x for x, _ in x_counts.most_common(n_cols * 4)]
    candidates.sort(key=lambda x: (-x_counts[x], x))
    chosen: list[int] = []
    for x in candidates:
        if all(abs(x - c) > tol for c in chosen):
            chosen.append(x)
        if len(chosen) == n_cols:
            break
    chosen.sort()
    if not chosen:
        return []
    cols: list[list] = [[] for _ in chosen]
    for w in words:
        dx = [abs(w["x0"] - cx) for cx in chosen]
        i = dx.index(min(dx))
        if dx[i] <= tol:
            cols[i].append(w)
    for c in cols:
        c.sort(key=lambda w: w["top"])
    return cols


def _page_body(page) -> list:
    """Return body words for a page, skipping the intro paragraph if it's present.

    ARRL pages that carry the preamble paragraph have the centered title
    "ARRL DXCC ..." at y≈56. Those pages' data starts at y≈210. Other pages
    (continuation pages) start data at y≈45.
    """
    words = page.extract_words()
    has_intro = any(
        50 <= w["top"] <= 65 and w["text"] == "ARRL" and 200 <= w["x0"] <= 300
        for w in words
    )
    y_min = 200 if has_intro else 30
    return [w for w in words if y_min < w["top"] < 740]


def parse_band_pdf(data: bytes) -> dict[str, int]:
    """Parse an ARRL per-band or per-mode DXCC standings PDF.

    Layout: reading order is column-by-column (6 cols), top-to-bottom.
    A plain integer (>=100) is a DXCC count; subsequent callsigns carry
    that count until the next integer. Counts carry across columns/pages.
    """
    result: dict[str, int] = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        current_count: int | None = None
        for page in pdf.pages:
            body = _page_body(page)
            if not body:
                continue
            cols = cluster_columns(body, n_cols=6)
            reading_order = [w for col in cols for w in col]
            for w in reading_order:
                t = w["text"].strip()
                if not t:
                    continue
                if t.isdigit():
                    n = int(t)
                    if n >= 100:
                        current_count = n
                    continue
                if VU_RE.match(t) and current_count is not None:
                    call = _clean_call(t)
                    if call not in result or current_count > result[call]:
                        result[call] = current_count
    return result


def parse_hr_pdf(data: bytes, section: str = "Mixed") -> dict[str, int]:
    """Parse ARRL Honor Roll PDF. Returns {call: count} for the requested section.

    Format: sections labelled "Mixed" / "Phone" / "CW" / "Digital".
    Entries look like "4X4DK/395".
    """
    result: dict[str, int] = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        current_section: str | None = None
        for page in pdf.pages:
            body = _page_body(page)
            if not body:
                continue
            cols = cluster_columns(body, n_cols=6)
            reading_order = [w for col in cols for w in col]
            for w in reading_order:
                t = w["text"].strip()
                if t in ("Mixed", "Phone", "CW", "Digital"):
                    current_section = t
                    continue
                if "/" not in t or current_section != section:
                    continue
                call, _, count_s = t.rpartition("/")
                if not count_s.isdigit():
                    continue
                if VU_RE.match(call):
                    call_base = _clean_call(call)
                    n = int(count_s)
                    if call_base not in result or n > result[call_base]:
                        result[call_base] = n
    return result


# ---------- aggregation ----------

def aggregate(all_results: dict[str, dict[str, int]]) -> list[dict]:
    calls: set[str] = set()
    for m in all_results.values():
        calls.update(m.keys())
    rows: list[dict] = []
    for call in calls:
        row: dict = {"callsign": call}
        for k, _, _, _ in CATEGORIES:
            row[k] = all_results.get(k, {}).get(call)
        rows.append(row)

    def sort_key(r):
        vals = [r[k] for k in BAND_MODE_KEYS if r[k] is not None]
        return (-(max(vals) if vals else 0), r["callsign"])

    rows.sort(key=sort_key)
    for i, r in enumerate(rows):
        r["sno"] = i + 1
    return rows


# ---------- diff against previous snapshot ----------

def load_previous(path: Path) -> dict:
    """Load a prior data.json and return a lookup: {callsign: {col_key: value_or_None}}."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  (previous snapshot unreadable — {exc}; skipping diff)", file=sys.stderr)
        return {}
    lookup: dict[str, dict[str, int | None]] = {}
    cat_keys = [c[0] for c in CATEGORIES]
    for r in payload.get("rows", []):
        call = r.get("callsign")
        if not call:
            continue
        lookup[call] = {k: r.get(k) for k in cat_keys}
    return {"rows": lookup, "as_on": payload.get("as_on")}


def annotate_diffs(rows: list[dict], previous: dict) -> None:
    """Mutate each row in-place, adding `_changes` (list of changed col keys) and
    `_is_new` (bool) based on comparison with the previous snapshot.

    A cell is considered "changed" if its value differs from the prior one,
    including transitions between a number and None (new entry, dropped entry).
    """
    prev_rows: dict[str, dict] = previous.get("rows", {}) if previous else {}
    for r in rows:
        if not prev_rows:
            r["_changes"] = []
            r["_is_new"] = False
            continue
        call = r["callsign"]
        prev = prev_rows.get(call)
        if prev is None:
            r["_is_new"] = True
            r["_changes"] = [k for k, _, _, _ in CATEGORIES if r.get(k) is not None]
        else:
            r["_is_new"] = False
            r["_changes"] = [
                k for k, _, _, _ in CATEGORIES
                if (r.get(k) or None) != (prev.get(k) or None)
            ]


# ---------- output PDF ----------

def generate_pdf(
    rows: list[dict],
    as_on_date: str,
    output_path: Path,
    previous_as_on: str | None = None,
) -> None:
    pagesize = landscape(A4)
    doc = SimpleDocTemplate(
        str(output_path), pagesize=pagesize,
        leftMargin=8 * mm, rightMargin=8 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm,
    )
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("title", parent=styles["Heading2"], fontSize=12, alignment=TA_LEFT, spaceAfter=0)
    right_s = ParagraphStyle("right", parent=styles["Normal"], fontSize=10, alignment=TA_RIGHT)
    notes_s = ParagraphStyle("notes", parent=styles["Normal"], fontSize=7, textColor=colors.grey)

    elements = [
        Table(
            [[Paragraph("<b>VU DXCC List</b>", title_s),
              Paragraph(f"<b>As on:</b> {as_on_date}", right_s)]],
            colWidths=[80 * mm, 200 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]),
        ),
        Spacer(1, 4),
    ]

    headers = ["#", "Callsign"] + [c[2] for c in CATEGORIES]
    data: list[list] = [headers]
    for r in rows:
        row = [r["sno"], r["callsign"]]
        for k, _, _, _ in CATEGORIES:
            v = r[k]
            row.append(v if v is not None else "")
        data.append(row)

    n_vals = len(CATEGORIES)
    total_w = pagesize[0] - 16 * mm
    sno_w = 7 * mm
    call_w = 17 * mm
    val_w = (total_w - sno_w - call_w) / n_vals
    col_widths = [sno_w, call_w] + [val_w] * n_vals

    col_max: dict[str, int | None] = {}
    for k, _, _, _ in CATEGORIES:
        vals = [r[k] for r in rows if r[k] is not None]
        col_max[k] = max(vals) if vals else None

    style_cmds: list = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bcc3ce")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a56db")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f5f9")))

    for ci, (k, _, _, _) in enumerate(CATEGORIES):
        mx = col_max[k]
        if mx is None:
            continue
        col_idx = 2 + ci
        for ri, r in enumerate(rows):
            if r[k] == mx:
                style_cmds.append(("BACKGROUND", (col_idx, ri + 1), (col_idx, ri + 1), colors.HexColor("#c6e8b0")))

    # Changed-since-last-snapshot highlight (takes precedence over green max BG)
    change_bg = colors.HexColor("#ffe0e0")
    new_row_bg = colors.HexColor("#ffd0d0")
    cat_col_index = {k: 2 + i for i, (k, _, _, _) in enumerate(CATEGORIES)}
    for ri, r in enumerate(rows):
        changes = r.get("_changes") or []
        if r.get("_is_new"):
            style_cmds.append(("BACKGROUND", (1, ri + 1), (1, ri + 1), new_row_bg))
        for k in changes:
            ci = cat_col_index[k]
            style_cmds.append(("BACKGROUND", (ci, ri + 1), (ci, ri + 1), change_bg))

    elements.append(Table(data, colWidths=col_widths, repeatRows=1, style=TableStyle(style_cmds)))
    elements.append(Spacer(1, 4))
    notes_bits = [
        "<b>Notes:</b>",
        f"Contains {len(rows)} VU callsigns sorted by max credits across band/mode columns "
        "(Mix, Ph, CW, Dig, Sat, 160\u20136\u00a0m), descending.",
        "Green background = maximum value in that column.",
    ]
    if previous_as_on:
        notes_bits.append(
            f"Light red background = changed since previous snapshot ({previous_as_on}); "
            "darker red on a callsign cell = entry is new."
        )
    notes_bits.append(
        "Data compiled from ARRL DXCC Standings published at arrl.org/dxcc-standings. "
        "Table layout adapted from the original VU DXCC list template by VU2DCC."
    )
    elements.append(Paragraph(" ".join(notes_bits), notes_s))
    doc.build(elements)


# ---------- CLI ----------

def today_token() -> str:
    return dt.date.today().strftime("%Y%m%d")


def pretty_date(date_str: str) -> str:
    try:
        return dt.datetime.strptime(date_str, "%Y%m%d").date().strftime("%d %b %Y")
    except ValueError:
        return date_str


def write_json(
    rows: list[dict],
    date_str: str,
    as_on: str,
    output_path: Path,
    previous_as_on: str | None = None,
) -> None:
    payload = {
        "as_on": as_on,
        "previous_as_on": previous_as_on,
        "date_token": date_str,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "columns": [c[0] for c in CATEGORIES],
        "column_labels": [c[2] for c in CATEGORIES],
        "band_mode_columns": BAND_MODE_KEYS,
        "rows": [
            {
                "sno": r["sno"],
                "callsign": r["callsign"],
                **{k: r[k] for k, _, _, _ in CATEGORIES},
                "changes": r.get("_changes") or [],
                "is_new": bool(r.get("_is_new")),
            }
            for r in rows
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a VU DXCC PDF from ARRL DXCC Standings.")
    ap.add_argument("--date", default=None, help="ARRL standings date as YYYYMMDD (default: today)")
    ap.add_argument("--output", default=None, help="Output PDF path")
    ap.add_argument("--json", dest="json_path", default=None, help="Also write JSON data to this path")
    ap.add_argument("--previous", dest="previous_path", default=None,
                    help="Path to a prior data.json; enables diff highlighting")
    ap.add_argument("--cache-dir", default=None, help="Cache dir for downloaded ARRL PDFs")
    ap.add_argument("--no-cache", action="store_true", help="Force re-download (ignore cache)")
    args = ap.parse_args(argv)

    date_str = args.date or today_token()
    script_dir = Path(__file__).parent.resolve()
    cache_dir = Path(args.cache_dir) if args.cache_dir else script_dir / "cache" / date_str
    output_path = Path(args.output) if args.output else script_dir / f"VUDXCC-{date_str}.pdf"

    print(f"VU DXCC generator — standings date: {pretty_date(date_str)}")
    print(f"Cache: {cache_dir}")

    all_results: dict[str, dict[str, int]] = {}
    for idx, (key, token, label, parser_type) in enumerate(CATEGORIES, 1):
        dest = cache_dir / f"DXCC-{token}-{date_str}.pdf"
        url = url_for(token, date_str)
        sys.stdout.write(f"  [{idx:2d}/{len(CATEGORIES)}] {label:>4} ")
        sys.stdout.flush()
        try:
            data = download_pdf(url, dest, use_cache=not args.no_cache)
            size_kb = len(data) / 1024
            if parser_type == "band":
                vu = parse_band_pdf(data)
            else:
                vu = parse_hr_pdf(data, section="Mixed")
            all_results[key] = vu
            print(f"  {size_kb:6.1f} kB  →  {len(vu):3d} VU")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")
            all_results[key] = {}

    rows = aggregate(all_results)
    print(f"\nAggregated {len(rows)} unique VU callsigns.")
    if not rows:
        print("No VU callsigns found — aborting PDF generation.", file=sys.stderr)
        return 1

    previous_payload: dict = {}
    previous_as_on: str | None = None
    if args.previous_path:
        prev_path = Path(args.previous_path)
        if prev_path.exists():
            previous_payload = load_previous(prev_path)
            previous_as_on = previous_payload.get("as_on")
            print(f"Diffing against previous snapshot: {prev_path} (as on {previous_as_on})")
        else:
            print(f"No previous snapshot at {prev_path}; skipping diff.")
    annotate_diffs(rows, previous_payload)

    n_changed = sum(1 for r in rows if r.get("_changes"))
    n_new = sum(1 for r in rows if r.get("_is_new"))
    if previous_payload:
        print(f"Changes vs previous: {n_changed} row(s) with updates, {n_new} new callsign(s).")

    generate_pdf(rows, pretty_date(date_str), output_path, previous_as_on=previous_as_on)
    print(f"Wrote: {output_path}")

    if args.json_path:
        json_path = Path(args.json_path)
        write_json(rows, date_str, pretty_date(date_str), json_path,
                   previous_as_on=previous_as_on)
        print(f"Wrote: {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
