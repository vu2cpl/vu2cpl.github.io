# VU DXCC Credits

Live VU DXCC standings page, auto-refreshed monthly from the
[ARRL DXCC Standings](https://www.arrl.org/dxcc-standings) publication.

Live at **[vu2cpl.com/dxcc/](https://vu2cpl.com/dxcc/)**.

## What's here

| File | Purpose |
| --- | --- |
| `index.html` | Sortable table UI that fetches `data.json` in-browser. Callsigns link to [qrz.com/db/](https://www.qrz.com/db/). |
| `data.json` | Generated — current VU DXCC data (one row per callsign) |
| `data.previous.json` | Generated — prior snapshot kept for month-over-month diffs |
| `VUDXCC-latest.pdf` | Generated — printable PDF in the classic VU DXCC layout |
| `vudxcc.py` | Generator script (Python) |
| `requirements.txt` | Python dependencies (`pdfplumber`, `reportlab`) |

## Cell highlighting

| Colour | Meaning |
| --- | --- |
| Green | Leader (maximum value) in that band/mode column |
| Light red | Cell value changed vs the previous snapshot |
| Darker red (on callsign) | Brand-new callsign since the previous snapshot |

The legend bar above the table shows the total number of changed cells and new
callsigns, plus the previous snapshot's date, whenever a diff baseline exists.

## How the refresh works

The workflow at `.github/workflows/refresh-vu-dxcc.yml` runs on the
**5th of each month** (and on manual dispatch). It:

1. Copies the current `data.json` to `data.previous.json` so the fresh run
   has a diff baseline.
2. Downloads the 17 ARRL DXCC Standings PDFs (Mixed, Phone, CW, Digital,
   Satellite, each band 160–6 m, Challenge, Honor Roll).
3. Parses every PDF and collects every callsign starting with `VU`.
4. Compares every cell to `data.previous.json` and flags changed cells +
   brand-new callsigns.
5. Writes `data.json` (with change flags embedded) and `VUDXCC-latest.pdf`.
6. Commits the regenerated files back to the repo.

To force a refresh before the 5th: **Actions → Refresh VU DXCC list →
Run workflow**.

## Running locally

```bash
cd dxcc
pip install -r requirements.txt
python vudxcc.py --output VUDXCC-latest.pdf --json data.json
# Open index.html via any static server:
python -m http.server 8000
# then visit http://localhost:8000/
```

Options:
- `--date YYYYMMDD` — fetch a specific ARRL snapshot date.
- `--previous PATH` — diff against a prior `data.json` (enables red highlighting).
- `--no-cache` — force re-download (default caches under `cache/`).

## Credits

- Data source: [ARRL DXCC Standings](https://www.arrl.org/dxcc-standings).
- Table layout adapted from the original VU DXCC list template by **VU2DCC**.
