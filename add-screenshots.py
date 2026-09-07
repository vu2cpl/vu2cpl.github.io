#!/usr/bin/env python3
"""Merge screenshots into a project page at /projects/<slug>/.

    ./add-screenshots.py dxca ~/Desktop/spots.png ~/Desktop/alerts.png
    ./add-screenshots.py dxca --two-up shots/*.png
    ./add-screenshots.py dxca --list
    ./add-screenshots.py dxca --clear      # remove gallery + shots/

Copies the files into projects/<slug>/shots/, then rewrites that page's
gallery block. Rerunning REPLACES the gallery rather than appending, so the
command is idempotent — fix a caption, run it again with the same files.

Captions come from the filename: "01-spot-table.png" -> "Spot table".
Rename the file to change the caption; that keeps the caption and the image
in one place instead of in a sidecar nobody updates.
"""
import sys, os, re, shutil, glob

ROOT = os.path.dirname(os.path.abspath(__file__))
OK_EXT = {'.png', '.jpg', '.jpeg', '.webp'}
WARN_BYTES = 1_500_000

def caption_from(name):
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r'^\d+[-_]', '', stem)             # drop ordering prefix
    stem = re.sub(r'[-_]+', ' ', stem).strip()
    return stem[:1].upper() + stem[1:] if stem else 'Screenshot'

def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))

def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__); return 0
    slug, rest = argv[0], argv[1:]
    page = os.path.join(ROOT, 'projects', slug, 'index.html')
    if not os.path.isfile(page):
        avail = sorted(os.path.basename(os.path.dirname(p))
                       for p in glob.glob(os.path.join(ROOT, 'projects', '*', 'index.html')))
        print(f"No project page for '{slug}'.\nAvailable: {', '.join(avail)}")
        return 1

    shots_dir = os.path.join(ROOT, 'projects', slug, 'shots')
    if '--list' in rest:
        for f in sorted(glob.glob(os.path.join(shots_dir, '*'))):
            print(f"  {os.path.basename(f):40s} {os.path.getsize(f)/1024:7.0f} KB  \"{caption_from(f)}\"")
        return 0

    if '--clear' in rest:
        s = open(page, encoding='utf-8').read()
        s2 = re.sub(r'  <div class="proj-shots-label">.*?</div>\n  <div class="proj-shots.*?</div>\n',
                    '', s, flags=re.S)
        open(page, 'w', encoding='utf-8').write(s2)
        if os.path.isdir(shots_dir):
            shutil.rmtree(shots_dir)
        print(f"cleared gallery and shots/ for {slug}"
              if s2 != s else f"{slug} had no gallery; shots/ removed if present")
        return 0

    two_up = '--two-up' in rest
    files = [f for f in rest if not f.startswith('--')]
    if not files:
        print("No image files given. Use --list to see what is already there.")
        return 1

    bad = [f for f in files if os.path.splitext(f)[1].lower() not in OK_EXT]
    if bad:
        print("Not an image type this site serves:", ', '.join(bad)); return 1
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        print("Not found:", ', '.join(missing)); return 1

    os.makedirs(shots_dir, exist_ok=True)
    entries = []
    for i, src in enumerate(files, 1):
        ext = os.path.splitext(src)[1].lower().replace('.jpeg', '.jpg')
        stem = re.sub(r'[^a-z0-9]+', '-', caption_from(src).lower()).strip('-')
        dest_name = f"{i:02d}-{stem}{ext}"
        dest = os.path.join(shots_dir, dest_name)
        shutil.copy2(src, dest)
        size = os.path.getsize(dest)
        if size > WARN_BYTES:
            print(f"  ! {dest_name} is {size/1_000_000:.1f} MB — consider resizing to <2000px wide")
        entries.append((dest_name, caption_from(src), size))

    cap_attr = lambda c: esc(c)
    figs = []
    for name, cap, _ in entries:
        figs.append(
f"""    <figure>
      <a class="shack-zoom" href="shots/{name}" data-caption="{cap_attr(cap)}">
        <img src="shots/{name}" alt="{cap_attr(cap)} — {esc(slug)}" loading="lazy">
      </a>
      <figcaption>{esc(cap)}</figcaption>
    </figure>""")

    block = ('  <div class="proj-shots-label">Screenshots</div>\n'
             f'  <div class="proj-shots{" two-up" if two_up else ""}">\n'
             + '\n'.join(figs) + '\n  </div>\n')

    s = open(page, encoding='utf-8').read()
    s = re.sub(r'  <div class="proj-shots-label">.*?</div>\n  <div class="proj-shots.*?</div>\n',
               '', s, flags=re.S)                                   # drop any previous gallery
    anchor = '  <div class="project-tags">'
    assert anchor in s, 'page layout changed — update this script'
    s = s.replace(anchor, block + anchor, 1)
    open(page, 'w', encoding='utf-8').write(s)

    total = sum(e[2] for e in entries)
    print(f"{len(entries)} screenshot(s) -> projects/{slug}/shots/  ({total/1024:.0f} KB total)")
    for name, cap, size in entries:
        print(f'  {name:40s} "{cap}"')
    print(f"\nPreview:  python3 -m http.server 8766 --directory {ROOT}")
    print(f"          http://localhost:8766/projects/{slug}/")
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
