"""draw.io XML export for the accumulated session graph.

ChainOps' take on StealthOps' still-unbuilt `draw` command (see
StealthOps/ROADMAP.md) — address graphs are a more natural fit than
infra graphs here: instead of synthesizing entities from disparate
WHOIS/DNS/enrichment fields, the session graph already IS a node/edge
structure (graph.expand_neighbors / console.ConsoleSession). This module
just renders it as mxGraphModel XML; draw.io's own auto-layout is
expected to tidy the approximate ring positions we assign, same
disclaimer StealthOps' spec makes for its own planned version.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RING_RADIUS_STEP = 220
_NODE_WIDTH = 160
_NODE_HEIGHT = 40

# (fill, stroke) by depth; last entry repeats for any deeper ring.
_DEPTH_COLORS = [
    ("#dae8fc", "#6c8ebf"),  # depth 0 (seed) - blue
    ("#d5e8d4", "#82b366"),  # depth 1 - green
    ("#ffe6cc", "#d79b00"),  # depth 2 - orange
    ("#f8cecc", "#b85450"),  # depth 3+ - red
]


def _short_label(address: str) -> str:
    if len(address) <= 16:
        return address
    return f"{address[:8]}...{address[-6:]}"


def _node_color(depth: int) -> tuple[str, str]:
    return _DEPTH_COLORS[min(depth, len(_DEPTH_COLORS) - 1)]


def _edge_label(edge: dict[str, Any]) -> str:
    """BTC edges carry value_sats; Tron/EVM token-transfer edges carry
    value (already decimal) + symbol -- see graph.py's edge shapes."""
    if "value_sats" in edge:
        return f"{edge.get('value_sats', 0) / 1e8:.8f} BTC"
    value = edge.get("value")
    symbol = edge.get("symbol") or ""
    if value is None:
        return symbol
    return f"{value:.6f} {symbol}".strip()


def _ring_position(depth: int, index: int, count: int) -> tuple[float, float]:
    if depth == 0:
        return 0.0, 0.0
    radius = depth * _RING_RADIUS_STEP
    angle = (2 * math.pi * index) / max(count, 1)
    return radius * math.cos(angle), radius * math.sin(angle)


def build_drawio_xml(
    nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], seed: str | None = None
) -> str:
    """Render a session graph (nodes: {address: {"depth": int}}, edges:
    [{"from", "to", "value_sats", ...}]) as draw.io mxGraphModel XML.
    """
    model = ET.Element(
        "mxGraphModel",
        {
            "dx": "800",
            "dy": "600",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "1100",
            "pageHeight": "850",
            "math": "0",
            "shadow": "0",
        },
    )
    root_container = ET.SubElement(model, "root")
    ET.SubElement(root_container, "mxCell", {"id": "0"})
    ET.SubElement(root_container, "mxCell", {"id": "1", "parent": "0"})

    by_depth: dict[int, list[str]] = {}
    for addr, info in nodes.items():
        by_depth.setdefault(info.get("depth", 0), []).append(addr)

    node_ids: dict[str, str] = {}
    for depth in sorted(by_depth):
        addrs = sorted(by_depth[depth])
        for i, addr in enumerate(addrs):
            x, y = _ring_position(depth, i, len(addrs))
            fill, stroke = _node_color(depth)
            node_id = f"n{len(node_ids)}"
            node_ids[addr] = node_id
            is_seed = addr == seed
            style = f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
            if is_seed:
                style += "fontStyle=1;strokeWidth=3;"
            label = _short_label(addr) + (" (seed)" if is_seed else "")
            cell = ET.SubElement(
                root_container,
                "mxCell",
                {"id": node_id, "value": label, "style": style, "vertex": "1", "parent": "1"},
            )
            ET.SubElement(
                cell,
                "mxGeometry",
                {
                    "x": f"{x - _NODE_WIDTH / 2:.1f}",
                    "y": f"{y - _NODE_HEIGHT / 2:.1f}",
                    "width": str(_NODE_WIDTH),
                    "height": str(_NODE_HEIGHT),
                    "as": "geometry",
                },
            )

    edge_count = 0
    for edge in edges:
        source_id = node_ids.get(edge.get("from"))
        target_id = node_ids.get(edge.get("to"))
        if source_id is None or target_id is None:
            continue
        edge_cell = ET.SubElement(
            root_container,
            "mxCell",
            {
                "id": f"e{edge_count}",
                "value": _edge_label(edge),
                "style": "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;",
                "edge": "1",
                "parent": "1",
                "source": source_id,
                "target": target_id,
            },
        )
        ET.SubElement(edge_cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        edge_count += 1

    return ET.tostring(model, encoding="unicode")


def save_drawio_file(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    seed: str | None = None,
    out_path: str | None = None,
) -> str:
    """Write the rendered graph to disk. Default path mirrors StealthOps'
    planned convention (~/Downloads/<product>-map-<timestamp>.drawio)."""
    xml_content = build_drawio_xml(nodes, edges, seed)
    if out_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_dir = Path.home() / "Downloads"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / f"chainops-map-{timestamp}.drawio")
    Path(out_path).write_text(xml_content, encoding="utf-8")
    return out_path
