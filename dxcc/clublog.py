#!/usr/bin/env python3
"""Build a VU/AT/AU DXCC standings list from Clublog's Asia Top-2000 confirmed league.

Fetches all 8 pages of the Clublog Asia DXCC league (2000 callsigns), filters for
Indian prefixes (VU / AT / AU), and emits:
  • clublog.json — machine-readable rows (same shape conventions as data.json)
  • VUDXCC-clublog-latest.pdf — printable list in the VU DXCC visual style

Usage:
    python3 clublog.py                                   # defaults: Asia + Confirmed + today
    python3 clublog.py --output VUDXCC-clublog.pdf       # custom PDF path
    python3 clublog.py --json clublog.json                # custom JSON path
    python3 clublog.py --previous clublog.previous.json   # diff vs prior snapshot
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CLUBLOG_URL = "https://clublog.org/league.php"

# Column order for Clublog output. "total" and "slots" are league metadata; the
# per-band columns mirror what Clublog publishes.
CATEGORIES: list[tuple[str, str]] = [
    ("160", "160"),
    ("80",  "80"),
    ("60",  "60"),
    ("40",  "40"),
    ("30",  "30"),
    ("20",  "20"),
    ("17",  "17"),
    ("15",  "15"),
    ("12",  "12"),
    ("10",  "10"),
    ("6",   "6"),
    ("total", "Total"),
    ("slots", "Slots"),
]
BAND_KEYS = [k for k, _ in CATEGORIES if k not in ("total", "slots")]

# Indian prefixes per ITU allocation. Users asked for VU / AT / AU.
INDIAN_RE = re.compile(r"^(VU|AT|AU)\d+[A-Z]+$")

# Clublog decorates callsigns with " ☆" or "+N" markers. Strip them.
DECORATION_RE = re.compile(r"[\s+][+\d☆★⭐]+\s*$|&#x[0-9a-fA-F]+;")


# ---------- network ----------

def fetch_page(page: int, *, continent: int = -4, confirmed: bool = True,
               current_only: bool = True, mode: int = 0) -> str:
    """POST Clublog's league form for one page (250 rows). Returns raw HTML."""
    body = urlencode({
        "SubmitDXCC": "Submit",
        "fMode":     mode,
        "fSlotSort": 0,      # 0 = Rank by DXCCs (matches "Total" column)
        "fSortBand": 0,      # Totals
        "fDeleted":  0 if current_only else 1,
        "fCfm":      1 if confirmed else 0,
        "fDate":     0,      # No date filter
        "fClub":     continent,  # -4 = Asia
        "page":      page,
    }).encode("utf-8")
    req = Request(
        CLUBLOG_URL,
        data=body,
        headers={
            "User-Agent": "vu-dxcc-tool/1.0 (+https://vu2cpl.com/dxcc/)",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---------- parsing ----------

def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return text.strip()


def _clean_callsign(raw: str) -> str | None:
    """Strip Clublog decorations and return the bare callsign, or None if malformed."""
    # Remove trailing " ☆" / "+1" / "+2" / "&#x2605;" style decorations
    s = re.sub(r"&#x[0-9a-fA-F]+;", "", raw)
    s = re.sub(r"[☆★⭐\*]+", "", s)
    s = re.sub(r"\+\d+", "", s)
    s = s.strip()
    # Uppercase and validate basic format
    m = re.match(r"^([A-Z0-9]{3,10})$", s.upper())
    return m.group(1) if m else None


def parse_league_page(html: str) -> list[dict]:
    """Return a list of row dicts for this page. No filtering applied."""
    m = re.search(r"<th>\s*Rank\s*</th>.*?</table>", html, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    chunk = m.group(0)
    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", chunk, re.DOTALL | re.IGNORECASE)

    results: list[dict] = []
    for row_html in rows_html:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.IGNORECASE)
        if len(tds) < 15:  # rank + call + 11 bands + total + slots + years
            continue
        vals = [_strip_tags(t) for t in tds]
        try:
            rank = int(vals[0])
        except ValueError:
            continue
        call = _clean_callsign(vals[1])
        if not call:
            continue

        def to_int(s: str) -> int | None:
            s = s.replace(",", "").strip()
            return int(s) if s.isdigit() else None

        # Expected column order after rank + call: 160 80 60 40 30 20 17 15 12 10 6 TOTAL SLOTS YEARS
        per_band_vals = [to_int(v) for v in vals[2:13]]
        total_val = to_int(vals[13]) if len(vals) > 13 else None
        slots_val = to_int(vals[14]) if len(vals) > 14 else None
        years_raw = vals[15] if len(vals) > 15 else ""

        row = {"rank": rank, "callsign": call}
        for k, v in zip(BAND_KEYS, per_band_vals):
            row[k] = v
        row["total"] = total_val
        row["slots"] = slots_val
        row["years"] = years_raw
        results.append(row)
    return results


# ---------- diff (mirrors vudxcc.py) ----------

def load_previous(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  (previous snapshot unreadable — {exc}; skipping diff)", file=sys.stderr)
        return {}
    cat_keys = [c[0] for c in CATEGORIES]
    lookup: dict[str, dict] = {}
    for r in payload.get("rows", []):
        call = r.get("callsign")
        if not call:
            continue
        lookup[call] = {k: r.get(k) for k in cat_keys}
    return {"rows": lookup, "as_on": payload.get("as_on")}


def annotate_diffs(rows: list[dict], previous: dict) -> None:
    prev_rows: dict = (previous or {}).get("rows", {})
    for r in rows:
        if not prev_rows:
            r["_changes"] = []
            r["_is_new"] = False
            continue
        prev = prev_rows.get(r["callsign"])
        if prev is None:
            r["_is_new"] = True
            r["_changes"] = [k for k, _ in CATEGORIES if r.get(k) is not None]
        else:
            r["_is_new"] = False
            r["_changes"] = [
                k for k, _ in CATEGORIES
                if (r.get(k) or None) != (prev.get(k) or None)
            ]


# ---------- PDF ----------

def generate_pdf(rows: list[dict], as_on: str, output_path: Path,
                 previous_as_on: str | None = None) -> None:
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
            [[Paragraph("<b>VU DXCC List — Clublog (Confirmed, Asia Top 2000)</b>", title_s),
              Paragraph(f"<b>As on:</b> {as_on}", right_s)]],
            colWidths=[140 * mm, 140 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]),
        ),
        Spacer(1, 4),
    ]

    headers = ["#", "Callsign"] + [label for _, label in CATEGORIES]
    data: list[list] = [headers]
    for i, r in enumerate(rows, 1):
        row = [i, r["callsign"]]
        for k, _ in CATEGORIES:
            v = r.get(k)
            row.append(v if v is not None else "")
        data.append(row)

    n_vals = len(CATEGORIES)
    total_w = pagesize[0] - 16 * mm
    sno_w = 8 * mm
    call_w = 20 * mm
    val_w = (total_w - sno_w - call_w) / n_vals
    col_widths = [sno_w, call_w] + [val_w] * n_vals

    col_max: dict = {}
    for k, _ in CATEGORIES:
        vals = [r.get(k) for r in rows if r.get(k) is not None]
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

    for ci, (k, _) in enumerate(CATEGORIES):
        mx = col_max[k]
        if mx is None:
            continue
        col_idx = 2 + ci
        for ri, r in enumerate(rows):
            if r.get(k) == mx:
                style_cmds.append(("BACKGROUND", (col_idx, ri + 1), (col_idx, ri + 1),
                                   colors.HexColor("#c6e8b0")))

    change_bg = colors.HexColor("#ffe0e0")
    new_bg = colors.HexColor("#ffd0d0")
    cat_col_index = {k: 2 + i for i, (k, _) in enumerate(CATEGORIES)}
    for ri, r in enumerate(rows):
        if r.get("_is_new"):
            style_cmds.append(("BACKGROUND", (1, ri + 1), (1, ri + 1), new_bg))
        for k in (r.get("_changes") or []):
            if k in cat_col_index:
                ci = cat_col_index[k]
                style_cmds.append(("BACKGROUND", (ci, ri + 1), (ci, ri + 1), change_bg))

    elements.append(Table(data, colWidths=col_widths, repeatRows=1, style=TableStyle(style_cmds)))
    elements.append(Spacer(1, 4))

    notes_bits = [
        "<b>Notes:</b>",
        f"Contains {len(rows)} Indian callsigns (VU / AT / AU) found in Clublog's Asia Top-2000 "
        "Confirmed league, sorted by Total DXCC descending.",
        "Green background = column maximum. ",
    ]
    if previous_as_on:
        notes_bits.append(
            f"Light red = value changed vs the {previous_as_on} snapshot; "
            "darker red on the callsign cell = newly-added entry."
        )
    notes_bits.append(
        "Data from Clublog's DXCC League (clublog.org/league.php). "
        "Table layout adapted from the original VU DXCC list template by VU2DCC."
    )
    elements.append(Paragraph(" ".join(notes_bits), notes_s))
    doc.build(elements)


# ---------- JSON ----------

def write_json(rows: list[dict], as_on: str, output_path: Path,
               previous_as_on: str | None = None) -> None:
    payload = {
        "source": "clublog",
        "as_on": as_on,
        "previous_as_on": previous_as_on,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "columns": [k for k, _ in CATEGORIES],
        "column_labels": [label for _, label in CATEGORIES],
        "band_mode_columns": BAND_KEYS,
        "rows": [
            {
                "sno": i + 1,
                "rank": r.get("rank"),
                "callsign": r["callsign"],
                **{k: r.get(k) for k, _ in CATEGORIES},
                "years": r.get("years", ""),
                "changes": r.get("_changes") or [],
                "is_new": bool(r.get("_is_new")),
            }
            for i, r in enumerate(rows)
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2))


# ---------- CLI ----------

def pretty_today() -> str:
    return dt.date.today().strftime("%d %b %Y")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a Clublog-based VU DXCC list.")
    ap.add_argument("--output", default="VUDXCC-clublog-latest.pdf", help="Output PDF path")
    ap.add_argument("--json", dest="json_path", default="clublog.json",
                    help="Output JSON path")
    ap.add_argument("--previous", dest="previous_path", default=None,
                    help="Path to prior clublog.json for diff highlighting")
    ap.add_argument("--pages", type=int, default=8,
                    help="Number of 250-row pages to pull (default 8 = top 2000)")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="Seconds to pause between page fetches (politeness)")
    args = ap.parse_args(argv)

    print(f"Clublog generator — pulling Asia top {args.pages * 250} confirmed league…")
    all_rows: list[dict] = []
    for p in range(1, args.pages + 1):
        sys.stdout.write(f"  page {p}/{args.pages} … ")
        sys.stdout.flush()
        try:
            html = fetch_page(p)
            page_rows = parse_league_page(html)
            all_rows.extend(page_rows)
            print(f"{len(page_rows)} rows")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED: {exc}")
        if p < args.pages:
            time.sleep(args.delay)

    # Filter for VU / AT / AU Indian callsigns
    indian_rows = [r for r in all_rows if INDIAN_RE.match(r["callsign"])]
    # Sort by Total DXCC desc, tie-break by callsign
    indian_rows.sort(key=lambda r: (-(r.get("total") or 0), r["callsign"]))
    print(f"\nScraped {len(all_rows)} Asian callsigns; {len(indian_rows)} are Indian (VU/AT/AU).")
    if not indian_rows:
        print("No Indian callsigns found — aborting.", file=sys.stderr)
        return 1

    previous_payload: dict = {}
    previous_as_on: str | None = None
    if args.previous_path:
        prev_path = Path(args.previous_path)
        if prev_path.exists():
            previous_payload = load_previous(prev_path)
            previous_as_on = previous_payload.get("as_on")
            print(f"Diffing against {prev_path} (as on {previous_as_on})")
        else:
            print(f"No previous snapshot at {prev_path}; skipping diff.")
    annotate_diffs(indian_rows, previous_payload)

    as_on = pretty_today()
    output = Path(args.output)
    json_path = Path(args.json_path)
    generate_pdf(indian_rows, as_on, output, previous_as_on=previous_as_on)
    print(f"Wrote: {output}")
    write_json(indian_rows, as_on, json_path, previous_as_on=previous_as_on)
    print(f"Wrote: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
