#!/usr/bin/env python3
"""Generate homelab architecture diagrams (self-contained HTML/SVG) from
network-architecture.yaml.

Follows the "diagram-design" skill conventions: editorial style guide
tokens, rounded orthogonal connectors, masked arrow labels, horizontal
bottom legend, and the accessible-SVG contract (role=img, title/desc).

Usage:
    python3 generate_diagrams.py [data.yaml] [output_dir]
"""
import sys
import math
import html
from pathlib import Path

import yaml

# ---- style-guide.md tokens (default skin) ---------------------------------
TOKENS = {
    "paper": "#f5f5f5",
    "ink": "#2d3142",
    "muted": "#4f5d75",
    "soft": "#7a8399",
    "rule": "rgba(45,49,66,0.12)",
    "accent": "#eb6c36",
    "accent_tint": "rgba(235,108,54,0.08)",
    "link": "#2e5aa8",
}

NODE_TREATMENT = {
    "focal": {"fill": TOKENS["accent_tint"], "stroke": TOKENS["accent"], "dash": None},
    "backend": {"fill": "#ffffff", "stroke": TOKENS["ink"], "dash": None},
    "store": {"fill": "rgba(45,49,66,0.05)", "stroke": TOKENS["muted"], "dash": None},
    "external": {"fill": "rgba(45,49,66,0.03)", "stroke": "rgba(45,49,66,0.30)", "dash": None},
    "input": {"fill": "rgba(79,93,117,0.10)", "stroke": TOKENS["soft"], "dash": None},
    "optional": {"fill": "rgba(45,49,66,0.02)", "stroke": "rgba(45,49,66,0.20)", "dash": "4,3"},
    "security": {"fill": "rgba(235,108,54,0.05)", "stroke": "rgba(235,108,54,0.50)", "dash": "4,4"},
}

EDGE_COLOR = {"muted": TOKENS["muted"], "accent": TOKENS["accent"], "link": TOKENS["link"]}

FONT_LINK = (
    '<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1'
    '&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" '
    'rel="stylesheet">'
)


def rounded_path(points, r=8):
    """Build an SVG path `d` string through axis-aligned waypoints with
    rounded (r=8) corners at every interior vertex."""
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        raise ValueError("need at least 2 points")
    if len(pts) == 2:
        (x0, y0), (x1, y1) = pts
        return f"M{x0},{y0} L{x1},{y1}"

    def unit(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length)

    d = f"M{pts[0][0]},{pts[0][1]}"
    for i in range(1, len(pts) - 1):
        x0y0, x1y1, x2y2 = pts[i - 1], pts[i], pts[i + 1]
        u_in = unit(x0y0, x1y1)
        u_out = unit(x1y1, x2y2)
        p_in = (x1y1[0] - u_in[0] * r, x1y1[1] - u_in[1] * r)
        p_out = (x1y1[0] + u_out[0] * r, x1y1[1] + u_out[1] * r)
        d += f" L{p_in[0]:.0f},{p_in[1]:.0f} Q{x1y1[0]},{x1y1[1]} {p_out[0]:.0f},{p_out[1]:.0f}"
    d += f" L{pts[-1][0]},{pts[-1][1]}"
    return d


def node_box(n):
    x, y, w, h = n["x"], n["y"], n["w"], n["h"]
    cx, cy = x + w / 2, y + h / 2
    treat = NODE_TREATMENT[n["type"]]
    dash_attr = f' stroke-dasharray="{treat["dash"]}"' if treat["dash"] else ""
    tag = n.get("tag", "")
    tag_w = max(24, 12 + len(tag) * 6)
    name = html.escape(n["name"])
    raw_sublabel = n.get("sublabel", "")
    sublabel_lines = raw_sublabel if isinstance(raw_sublabel, list) else ([raw_sublabel] if raw_sublabel else [])
    stroke_color = treat["stroke"]
    svg = []
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{TOKENS["paper"]}"/>')
    svg.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{treat["fill"]}" '
        f'stroke="{stroke_color}" stroke-width="1"{dash_attr}/>'
    )
    if tag:
        svg.append(
            f'<rect x="{x + 8}" y="{y + 6}" width="{tag_w}" height="12" rx="2" '
            f'fill="transparent" stroke="{TOKENS["ink"]}" stroke-opacity="0.35" stroke-width="0.8"/>'
        )
        svg.append(
            f'<text x="{x + 8 + tag_w / 2:.0f}" y="{y + 15}" fill="{TOKENS["ink"]}" '
            f'fill-opacity="0.55" font-size="7" font-family="\'Geist Mono\', monospace" '
            f'text-anchor="middle" letter-spacing="0.08em">{html.escape(tag)}</text>'
        )
    if len(sublabel_lines) > 1:
        # Multi-line sublabel: anchor the whole name+lines block from the
        # top (below the tag) instead of centering on cy, since the block
        # height varies with the number of lines.
        name_y = y + 34
        for i, line in enumerate(sublabel_lines):
            svg.append(
                f'<text x="{cx:.0f}" y="{name_y + 16 + i * 12:.0f}" fill="{TOKENS["muted"]}" font-size="9" '
                f'font-family="\'Geist Mono\', monospace" text-anchor="middle">{html.escape(line)}</text>'
            )
    else:
        name_y = cy - 2 if sublabel_lines else cy + 4
        if sublabel_lines:
            svg.append(
                f'<text x="{cx:.0f}" y="{cy + 16:.0f}" fill="{TOKENS["muted"]}" font-size="9" '
                f'font-family="\'Geist Mono\', monospace" text-anchor="middle">{html.escape(sublabel_lines[0])}</text>'
            )
    svg.append(
        f'<text x="{cx:.0f}" y="{name_y:.0f}" fill="{TOKENS["ink"]}" font-size="12" '
        f'font-weight="600" font-family="\'Geist\', sans-serif" text-anchor="middle">{name}</text>'
    )
    return "\n".join(svg)


def edge_svg(e, slug, idx):
    style = e.get("style", "muted")
    color = EDGE_COLOR[style]
    dashed = e.get("dashed", False)
    dash_attr = ' stroke-dasharray="4,3"' if dashed else ""
    stroke_w = "1" if dashed else "1.2"
    marker = f"arrow-{style}" if style != "muted" else "arrow"
    if "path" in e:
        d = e["path"]
    else:
        d = rounded_path(e["points"])
    label = e.get("label", "")
    parts = [f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{stroke_w}"{dash_attr} '
             f'marker-end="url(#{marker})"/>']
    if label and e.get("label_pos"):
        lx, ly = e["label_pos"]
        w = max(28, 12 + len(label) * 5)
        parts.append(
            f'<rect x="{lx - w / 2:.0f}" y="{ly - 9:.0f}" width="{w:.0f}" height="12" rx="2" '
            f'fill="{TOKENS["paper"]}"/>'
        )
        parts.append(
            f'<text x="{lx}" y="{ly:.0f}" fill="{TOKENS["soft"]}" font-size="8" '
            f'font-family="\'Geist Mono\', monospace" text-anchor="middle" '
            f'letter-spacing="0.06em">{html.escape(label)}</text>'
        )
    return "\n".join(parts)


def zone_svg(z):
    x, y, w, h = z["x"], z["y"], z["w"], z["h"]
    label = z["label"]
    label_w = max(60, 14 + len(label) * 5)
    label_x = x + 16
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
        f'fill="rgba(45,49,66,0.02)" stroke="rgba(45,49,66,0.10)" stroke-width="0.8"/>\n'
        f'<rect x="{label_x}" y="{y + 4}" width="{label_w}" height="12" rx="2" fill="{TOKENS["paper"]}"/>\n'
        f'<text x="{label_x + label_w / 2:.0f}" y="{y + 13}" fill="rgba(45,49,66,0.40)" font-size="7" '
        f'font-family="\'Geist Mono\', monospace" text-anchor="middle" letter-spacing="0.14em">'
        f'{html.escape(label)}</text>'
    )


def legend_svg(items, view_w, legend_y):
    parts = [
        f'<line x1="30" y1="{legend_y - 8}" x2="{view_w - 30}" y2="{legend_y - 8}" '
        f'stroke="rgba(45,49,66,0.10)" stroke-width="0.8"/>',
        f'<text x="30" y="{legend_y + 8}" fill="{TOKENS["muted"]}" font-size="8" '
        f'font-family="\'Geist Mono\', monospace" letter-spacing="0.14em">LEGEND</text>',
    ]
    x = 148
    for item in items:
        swatch = item["swatch"]
        label = item["label"]
        if swatch == "muted-dashed":
            line = f'<line x1="{x}" y1="{legend_y + 4}" x2="{x + 28}" y2="{legend_y + 4}" ' \
                   f'stroke="{TOKENS["muted"]}" stroke-width="1.2" stroke-dasharray="4,3"/>'
        else:
            color = EDGE_COLOR.get(swatch, TOKENS["muted"])
            line = f'<line x1="{x}" y1="{legend_y + 4}" x2="{x + 28}" y2="{legend_y + 4}" ' \
                   f'stroke="{color}" stroke-width="1.2"/>'
        parts.append(line)
        parts.append(
            f'<text x="{x + 36}" y="{legend_y + 8}" fill="{TOKENS["muted"]}" font-size="8" '
            f'font-family="\'Geist Mono\', monospace" letter-spacing="0.06em">{html.escape(label)}</text>'
        )
        x += 36 + len(label) * 7 + 32
    return "\n".join(parts)


def markers_defs():
    return f'''
    <marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="{TOKENS["muted"]}"/>
    </marker>
    <marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="{TOKENS["accent"]}"/>
    </marker>
    <marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="{TOKENS["link"]}"/>
    </marker>'''


def render_diagram(d):
    slug = d["slug"]
    view_w, view_h = d["view"]
    title = html.escape(d["title"])
    subtitle = html.escape(d.get("subtitle", ""))
    desc = html.escape(d["desc"])
    title_id = f"{slug}-title"
    desc_id = f"{slug}-desc"

    zones_svg = "\n".join(zone_svg(z) for z in d["zones"])
    edges_svg = "\n".join(edge_svg(e, slug, i) for i, e in enumerate(d["edges"]))
    nodes_svg = "\n".join(node_box(n) for n in d["nodes"])
    legend = legend_svg(d["legend"], view_w, d["legend_y"])

    svg = f'''<svg viewBox="0 0 {view_w} {view_h}" role="img" aria-labelledby="{title_id} {desc_id}"
     xmlns="http://www.w3.org/2000/svg" width="100%" height="auto">
  <title id="{title_id}">{title}</title>
  <desc id="{desc_id}">{desc}</desc>
  <defs>
    {markers_defs()}
  </defs>
  <rect width="100%" height="100%" fill="{TOKENS["paper"]}"/>
  {zones_svg}
  {edges_svg}
  {nodes_svg}
  {legend}
</svg>'''

    page = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{FONT_LINK}
<style>
  :root {{
    --paper: {TOKENS["paper"]};
    --ink: {TOKENS["ink"]};
    --muted: {TOKENS["muted"]};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 48px 32px;
    background: var(--paper);
    color: var(--ink);
    font-family: 'Geist', sans-serif;
  }}
  .wrap {{ max-width: 1120px; margin: 0 auto; }}
  .eyebrow {{
    font-family: 'Geist Mono', monospace;
    font-size: 11px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 0 0 8px 0;
  }}
  h1 {{
    font-family: 'Instrument Serif', serif;
    font-weight: 400;
    font-size: 1.75rem;
    margin: 0 0 8px 0;
  }}
  .subtitle {{
    color: var(--muted);
    font-size: 14px;
    margin: 0 0 32px 0;
  }}
  .diagram {{ width: 100%; overflow-x: auto; }}
  footer {{
    margin-top: 32px;
    padding-top: 16px;
    border-top: 1px solid rgba(45,49,66,0.12);
    font-family: 'Geist Mono', monospace;
    font-size: 10px;
    color: var(--muted);
  }}
</style>
</head>
<body>
  <div class="wrap">
    <p class="eyebrow">HOMELAB / NETWORKING</p>
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
    <div class="diagram">
{svg}
    </div>
    <footer>generated from docs/diagrams/network-architecture.yaml — edit the data file and rerun generate_diagrams.py to update</footer>
  </div>
</body>
</html>'''
    return page


def main():
    here = Path(__file__).parent
    data_path = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "network-architecture.yaml"
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else here

    data = yaml.safe_load(data_path.read_text())
    for d in data["diagrams"]:
        page = render_diagram(d)
        out_path = out_dir / f"{d['slug']}.html"
        out_path.write_text(page)
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
