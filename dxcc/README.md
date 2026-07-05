# VU DXCC Credits

Live VU DXCC standings page with two tabs:

- **LoTW** — from the [ARRL DXCC Standings](https://www.arrl.org/dxcc-standings),
  refreshed **monthly** (1st of each month).
- **Clublog** — Indian callsigns (VU / AT / AU) found in the
  [Clublog Asia Top-2000 Confirmed league](https://clublog.org/league.php),
  refreshed **daily** (02:30 UTC / 08:00 IST).

Live at **[vu2cpl.com/dxcc/](https://vu2cpl.com/dxcc/)**.

## What's here

| File | Purpose |
| --- | --- |
| `index.html` | Sortable tabbed UI that fetches `data.json` (LoTW) or `clublog.json` (Clublog). Callsigns link to [qrz.com/db/](https://www.qrz.com/db/). |
| `data.json` | Generated — current LoTW/ARRL data (one row per callsign) |
| `data.previous.json` | Generated — prior LoTW snapshot for diffs |
| `VUDXCC-latest.pdf` | Generated — printable LoTW PDF |
| `clublog.json` | Generated — current Clublog VU data |
| `clublog.previous.json` | Generated — prior Clublog snapshot for diffs |
| `VUDXCC-clublog-latest.pdf` | Generated — printable Clublog PDF |
| `vudxcc.py` | LoTW generator — parses ARRL PDFs via `pdfplumber` |
| `clublog.py` | Clublog generator — scrapes Clublog league via HTTP POST |
| `requirements.txt` | Python dependencies (`pdfplumber`, `reportlab`) |

## Cell highlighting

| Colour | Meaning |
| --- | --- |
| Green | Leader (maximum value) in that band/mode column |
| Light red | Cell value changed vs the previous snapshot |
| Darker red (on callsign) | Brand-new callsign since the previous snapshot |

## What the numbers mean (current vs deleted entities)

- **Hon (Honor Roll)** — **current-only** DXCC count. The Honor Roll PDF
  groups callsigns under subsection headers keyed by the operator's
  current-entity total (340, 339, 338, …). The `/NNN` suffix on each
  entry is the operator's overall total including deleted entities;
  we deliberately ignore it and record the subsection header, so an
  op with 340 current + 4 deleted entities shows as 340 in Hon, not
  344.
- **Mix / Ph / CW / Dig / Sat / 160–6 m / Chal** — ARRL's per-band and
  per-mode standings PDFs list a single number per operator: the total
  credited entities (or slots for Chal), which **includes deleted-entity
  credits**. ARRL doesn't publish current-only per-band/mode
  breakdowns; the Honor Roll PDF publishes current-only for HR-listed
  ops (typically ≥ 331) but only for those ops, and applying an overlay
  to just those callsigns would make one op measured on a different
  definition than the rest of the column. To keep the columns
  comparable we take ARRL's published totals as-is here — same
  definition for every op — and reserve the current-only number for
  the Hon column, where "current DXCC total" is the column's whole
  point. Example: VU2PTT's Mix = 340 in the standings PDF includes 4
  deleted-entity credits; his current-only Mixed total (334) shows in
  Hon rather than getting silently subtracted from Mix.

The legend bar above the table shows the total number of changed cells and new
callsigns, plus the previous snapshot's date, whenever a diff baseline exists.

## How the refresh works

### LoTW (monthly)

`.github/workflows/refresh-vu-dxcc.yml` runs on the **1st of each month**
(and on manual dispatch). It:

1. Copies the current `data.json` → `data.previous.json` for diff baseline.
2. Downloads the 17 ARRL DXCC Standings PDFs (Mixed, Phone, CW, Digital,
   Satellite, each band 160–6 m, Challenge, Honor Roll). Each download
   retries up to 4× with exponential backoff on transient timeouts.
3. Parses every PDF and collects every callsign starting with `VU`.
4. **Refuses to publish** if any cell would regress vs the previous
   snapshot — DXCC counts are monotonic per callsign; a decrease
   (or a value going to `null`) means an upstream fetch/parse failure,
   not real news. Pass `--allow-regression` for genuine ARRL corrections.
5. Flags cells that changed + newly-added callsigns vs the previous snapshot.
6. Writes `data.json` (with change flags) and `VUDXCC-latest.pdf`.
7. Commits the regenerated files back to the repo.

### Clublog (daily)

`.github/workflows/refresh-clublog.yml` runs **daily at 02:30 UTC**
(and on manual dispatch). It:

1. Copies the current `clublog.json` → `clublog.previous.json`.
2. POSTs to `clublog.org/league.php` 8 times (pages 1–8) to pull the
   full top-2000 Asian Confirmed league.
3. Filters for Indian prefixes (`VU` / `AT` / `AU`).
4. Flags changes vs the previous snapshot.
5. Writes `clublog.json` + `VUDXCC-clublog-latest.pdf`.
6. Commits back to the repo.

Both workflows share a concurrency group (`dxcc-refresh`) so they never
collide on the same push.

To force a refresh before the 1st: **Actions → Refresh VU DXCC list →
Run workflow**.

## Running locally

```bash
cd dxcc
pip install -r requirements.txt

# LoTW (ARRL) — pulls 17 PDFs, ~1 min
python vudxcc.py  --output VUDXCC-latest.pdf          --json data.json

# Clublog — scrapes 8 pages of the Asia Top-2000 league, ~15 s
python clublog.py --output VUDXCC-clublog-latest.pdf  --json clublog.json

# Serve the page locally:
python -m http.server 8000
# then visit http://localhost:8000/
```

Options (`vudxcc.py`):
- `--date YYYYMMDD` — fetch a specific ARRL snapshot date.
- `--previous PATH` — diff against a prior `data.json` (enables red highlighting
  and the no-regression safety check).
- `--no-cache` — force re-download (default caches under `cache/`).
- `--allow-regression` — bypass the no-regression check; only use for a
  documented ARRL correction that genuinely removes credits.

Options (`clublog.py`):
- `--previous PATH` — diff against a prior `clublog.json`.
- `--pages N` — number of 250-row pages to pull (default 8 = top 2000).
- `--delay SEC` — politeness pause between page fetches (default 1 s).

## Credits

- Data sources: [ARRL DXCC Standings](https://www.arrl.org/dxcc-standings)
  (LoTW tab) and [Clublog DXCC League](https://clublog.org/league.php) (Clublog tab).
- Callsign links go to [QRZ.com](https://www.qrz.com/db/).
- Table layout adapted from the original VU DXCC list template by **VU2DCC**.
