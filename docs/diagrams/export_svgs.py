#!/usr/bin/env python3
"""Export the diagram <svg> node out of each generated HTML file into a
standalone, portable .svg next to it — suitable for embedding in the repo
README via a normal markdown image tag.

Per diagram-design skill references/export.md:
  - extract the first <svg>...</svg> block
  - normalize rgba(...)/transparent fills+strokes to hex+opacity (some
    renderers, e.g. PowerPoint, choke on rgba())
  - inline the Google Fonts @import with XML-escaped ampersands
  - prepend the XML declaration

Usage: python3 export_svgs.py [*.html]
"""
import re
import sys
from pathlib import Path

FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1"
    "&amp;family=Geist:wght@400;500;600&amp;family=Geist+Mono:wght@400;500;600&amp;display=swap');"
)


def normalize_colors(svg: str) -> str:
    svg = re.sub(
        r'(fill|stroke)="rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d*\.?\d+)\s*\)"',
        lambda m: '{0}="#{1:02x}{2:02x}{3:02x}" {0}-opacity="{4}"'.format(
            m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
        ),
        svg,
    )
    svg = re.sub(r'(fill|stroke)="transparent"', r'\1="none"', svg)
    return svg


def export(html_path: Path) -> Path:
    src = html_path.read_text()
    match = re.search(r"<svg[\s\S]*?</svg>", src)
    if not match:
        raise SystemExit(f"no <svg> block found in {html_path}")
    svg = match.group(0)

    if 'xmlns="http://www.w3.org/2000/svg"' not in svg:
        svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)

    svg = normalize_colors(svg)

    style_block = f"<defs><style>{FONT_IMPORT}</style></defs>"
    if "<defs>" in svg:
        svg = svg.replace("<defs>", f"<defs><style>{FONT_IMPORT}</style>", 1)
    else:
        # insert right after </desc> (title/desc are first children of <svg>)
        svg = re.sub(r"(</desc>)", r"\1" + style_block, svg, count=1)

    out = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n"
    out_path = html_path.with_suffix(".svg")
    out_path.write_text(out)
    return out_path


def main():
    here = Path(__file__).parent
    targets = [Path(p) for p in sys.argv[1:]] or sorted(here.glob("*.html"))
    for t in targets:
        out = export(t)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
