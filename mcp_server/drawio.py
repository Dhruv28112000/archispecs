"""Architecture -> draw.io XML with a deterministic grid layout.

One row per tier (fixed order), components spaced on a grid, labelled edges,
colour by tier. Never ask the LLM for coordinates.

Usage: python mcp_server/drawio.py   (writes outputs/test.drawio from a sample)
"""
import html
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schemas import Architecture, Component, Connection  # noqa: E402

TIER_ORDER = ["Client", "Edge", "Service", "Data", "Messaging", "External"]
TIER_COLOURS = {  # (fill, stroke) from the draw.io default palette
    "Client": ("#dae8fc", "#6c8ebf"),
    "Edge": ("#d5e8d4", "#82b366"),
    "Service": ("#fff2cc", "#d6b656"),
    "Data": ("#f8cecc", "#b85450"),
    "Messaging": ("#e1d5e7", "#9673a6"),
    "External": ("#f5f5f5", "#666666"),
}
DRAFT_LABEL = "Draft — requires BA/Architect review"

BOX_W, BOX_H = 180, 70
GAP_X = 60
ROW_H = 140
LABEL_W = 110  # left column holding the tier names
TOP = 60       # space for the draft label


def _cell(root: ET.Element, attrs: dict[str, str], x: int = 0, y: int = 0, w: int = 0, h: int = 0,
          edge: bool = False) -> ET.Element:
    cell = ET.SubElement(root, "mxCell", attrs)
    geo = ET.SubElement(cell, "mxGeometry", {"as": "geometry"})
    if edge:
        geo.set("relative", "1")
    else:
        geo.attrib.update({"x": str(x), "y": str(y), "width": str(w), "height": str(h)})
    return cell


def architecture_to_drawio(arch: Architecture) -> tuple[str, list[str]]:
    """Return (uncompressed draw.io XML, warnings). Edges to unknown components are skipped."""
    ids = [c.id for c in arch.components]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate component ids: {sorted(duplicates)}")

    rows = [(tier, [c for c in arch.components if c.tier == tier]) for tier in TIER_ORDER]
    rows = [(tier, comps) for tier, comps in rows if comps]
    widest = max((len(comps) for _, comps in rows), default=0)
    canvas_w = widest * BOX_W + max(widest - 1, 0) * GAP_X

    mxfile = ET.Element("mxfile", {"host": "ArchiSpec"})
    diagram = ET.SubElement(mxfile, "diagram", {"id": "architecture", "name": "Architecture"})
    model = ET.SubElement(diagram, "mxGraphModel", {"grid": "1", "gridSize": "10"})
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    _cell(root, {"id": "draft-label", "value": DRAFT_LABEL, "vertex": "1", "parent": "1",
                 "style": "text;html=1;fontStyle=2;fontColor=#b85450;align=left;"},
          x=0, y=10, w=LABEL_W + canvas_w, h=30)

    for row, (tier, comps) in enumerate(rows):
        y = TOP + row * ROW_H
        _cell(root, {"id": f"tier-{tier}", "value": tier, "vertex": "1", "parent": "1",
                     "style": "text;html=1;fontStyle=1;align=left;verticalAlign=middle;"},
              x=0, y=y, w=LABEL_W - 10, h=BOX_H)
        row_w = len(comps) * BOX_W + (len(comps) - 1) * GAP_X
        x0 = LABEL_W + (canvas_w - row_w) // 2  # centre each row under the widest one
        fill, stroke = TIER_COLOURS[tier]
        dashed = "dashed=1;" if tier == "External" else ""
        for col, comp in enumerate(comps):
            label = f"<b>{html.escape(comp.name)}</b><br><i>{html.escape(comp.tech)}</i>"
            _cell(root, {"id": f"c-{comp.id}", "value": label, "vertex": "1", "parent": "1",
                         "style": f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};"
                                  f"strokeColor={stroke};{dashed}"},
                  x=x0 + col * (BOX_W + GAP_X), y=y, w=BOX_W, h=BOX_H)

    warnings = []
    known = set(ids)
    for n, conn in enumerate(arch.connections):
        if conn.source not in known or conn.target not in known:
            warnings.append(f"Skipped edge {conn.source} -> {conn.target}: unknown component id")
            continue
        _cell(root, {"id": f"e-{n}", "value": html.escape(conn.label), "edge": "1", "parent": "1",
                     "source": f"c-{conn.source}", "target": f"c-{conn.target}",
                     "style": "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;"
                              "labelBackgroundColor=#ffffff;"},
              edge=True)

    ET.indent(mxfile)
    return ET.tostring(mxfile, encoding="unicode"), warnings


def write_drawio(arch: Architecture, path: Path) -> dict:
    """Write the diagram to `path`; return {path, components, connections, warnings}."""
    xml, warnings = architecture_to_drawio(arch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    return {"path": str(path), "components": len(arch.components),
            "connections": len(arch.connections) - len(warnings), "warnings": warnings}


SAMPLE = Architecture(
    components=[
        Component(id="web", name="Checkout Web", tech="Next.js", tier="Client", requirements=["FR-1"]),
        Component(id="api", name="Checkout API", tech="FastAPI", tier="Service", requirements=["FR-2"]),
        Component(id="wallet", name="Wallet Service", tech="FastAPI", tier="Service", requirements=["FR-8"]),
        Component(id="db", name="Orders & Wallet DB", tech="PostgreSQL", tier="Data", requirements=["DR-3"]),
        Component(id="events", name="Domain Events", tech="Kafka", tier="Messaging", requirements=["INT-2"]),
        Component(id="psp", name="PayBridge Gateway", tech="PayBridge (PSP)", tier="External", requirements=["FR-7"]),
    ],
    connections=[
        Connection(source="web", target="api", label="HTTPS / place order"),
        Connection(source="api", target="wallet", label="debit wallet"),
        Connection(source="api", target="psp", label="authorise card token"),
        Connection(source="api", target="db", label="orders"),
        Connection(source="wallet", target="db", label="balances"),
        Connection(source="api", target="events", label="OrderPlaced (outbox)"),
    ],
)

if __name__ == "__main__":
    out = ROOT / os.getenv("OUTPUT_DIR", "outputs") / "test.drawio"
    print(write_drawio(SAMPLE, out))
