"""PDF report generation for ChainOps — per-address and per-cluster,
per the roadmap. Mirrors StealthOps' report.py approach (parse the
already-generated formatted text into styled PDF blocks) since
formatter.format_cli_report()'s "=== SECTION === [source: ...]" /
"Label: value" convention is deliberately the same shape. Uses fpdf2's
core Helvetica/Courier fonts rather than StealthOps' custom TTF loading —
simpler, and this is a v1.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from formatter import format_cli_report

_LABEL_VALUE_RE = re.compile(r"^(\s*(?:-\s+)?)([A-Za-z][^:\n]{0,45}?)(: )(.+)$")

_NAVY = (15, 45, 90)
_TEAL = (0, 75, 110)
_LIGHT = (220, 235, 245)
_BODY = (20, 20, 20)

_HDR_FONT = "Helvetica"
_MONO_FONT = "Courier"


def _safe(text: str) -> str:
    """Strip ANSI codes (none expected from our formatter, but cheap
    insurance) and coerce to Latin-1 for PDF core fonts."""
    stripped = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return stripped.encode("latin-1", errors="replace").decode("latin-1")


def _resolve_path(name: str, out_path: str | None) -> Path:
    if out_path:
        return Path(out_path).expanduser().resolve()
    safe_name = re.sub(r"[^\w.\-]", "_", name)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    downloads = Path.home() / "Downloads"
    base_dir = downloads if downloads.is_dir() else Path.home()
    return base_dir / f"chainops-{safe_name}-{ts}.pdf"


def _require_fpdf() -> Any:
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError("PDF generation requires fpdf2. Install with: pip install fpdf2") from exc
    return FPDF


def generate_address_report(target: str, result: dict[str, Any], out_path: str | None = None) -> Path:
    """PDF case report for a single address, from a run_all_staged() result."""
    FPDF = _require_fpdf()
    body_text = _safe(format_cli_report(result))
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line_h = 4.5

    class _Doc(FPDF):
        def footer(self) -> None:
            self.set_y(-12)
            self.set_font(_HDR_FONT, "", 7)
            self.set_text_color(150, 150, 150)
            self.cell(0, 6, text=_safe(f"Page {self.page_no()}  |  ChainOps  |  {target}"), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf = _Doc(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(left=12, top=12, right=12)
    pdf.add_page()

    pdf.set_fill_color(*_NAVY)
    pdf.set_text_color(*_LIGHT)
    pdf.set_font(_HDR_FONT, "B", 15)
    pdf.cell(0, 11, text="ChainOps  Case Report", fill=True, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font(_HDR_FONT, "", 8)
    pdf.cell(0, 7, text=_safe(f"Target: {target}   |   Generated: {ts_str}"), fill=True, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_fill_color(255, 255, 255)
    pdf.set_text_color(*_BODY)
    pdf.ln(5)

    for raw_line in body_text.splitlines():
        line = raw_line.replace("\t", "    ")

        if line.startswith("==="):
            pdf.ln(1)
            pdf.set_font(_HDR_FONT, "B", 9)
            pdf.set_fill_color(*_TEAL)
            pdf.set_text_color(*_LIGHT)
            pdf.cell(0, 6, text=_section_label(line), fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*_BODY)
            pdf.ln(1)
        elif not line.strip():
            pdf.ln(2)
        else:
            match = _LABEL_VALUE_RE.match(line)
            if match:
                prefix, label, _, value = match.groups()
                if prefix:
                    pdf.set_font(_MONO_FONT, "", 7.5)
                    pdf.write(line_h, text=prefix)
                pdf.set_font(_MONO_FONT, "B", 7.5)
                pdf.write(line_h, text=label + ":")
                pdf.set_font(_MONO_FONT, "", 7.5)
                pdf.write(line_h, text=" " + value)
                pdf.ln(line_h)
            else:
                pdf.set_font(_MONO_FONT, "", 7.5)
                pdf.cell(0, line_h, text=line, new_x="LMARGIN", new_y="NEXT")

    dest = _resolve_path(target, out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dest))
    return dest


def _section_label(line: str) -> str:
    parts = [p.strip() for p in line.split("===") if p.strip()]
    if not parts:
        return line.strip()
    title = parts[0]
    if len(parts) >= 2:
        source = parts[1].strip("[] ").strip()
        return f"{title}  |  {source}"
    return title


_CLUSTER_TABLE_COLUMNS = ["address", "balance_btc", "tx_count", "dormancy_days", "sanctions_hit", "risk_flags"]


def generate_cluster_report(cluster_id: str, rows: list[dict[str, Any]], out_path: str | None = None) -> Path:
    """PDF case report for a cluster of addresses. `rows` are
    bulk.TRIAGE_FIELDNAMES-shaped dicts for that cluster's members only —
    callers are responsible for filtering (e.g. by cluster_id) before
    calling this.
    """
    FPDF = _require_fpdf()
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _num(row: dict[str, Any], field: str) -> float:
        value = row.get(field)
        return float(value) if isinstance(value, (int, float)) else 0.0

    total_balance = sum(_num(r, "balance_btc") for r in rows)
    total_tx_count = sum(_num(r, "tx_count") for r in rows)
    sanctioned_count = sum(1 for r in rows if r.get("sanctions_hit") is True)

    class _Doc(FPDF):
        def footer(self) -> None:
            self.set_y(-12)
            self.set_font(_HDR_FONT, "", 7)
            self.set_text_color(150, 150, 150)
            self.cell(0, 6, text=_safe(f"Page {self.page_no()}  |  ChainOps  |  cluster {cluster_id}"), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf = _Doc(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(left=12, top=12, right=12)
    pdf.add_page()

    pdf.set_fill_color(*_NAVY)
    pdf.set_text_color(*_LIGHT)
    pdf.set_font(_HDR_FONT, "B", 15)
    pdf.cell(0, 11, text="ChainOps  Cluster Report", fill=True, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font(_HDR_FONT, "", 8)
    pdf.cell(0, 7, text=_safe(f"Cluster: {cluster_id}   |   Generated: {ts_str}"), fill=True, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_fill_color(255, 255, 255)
    pdf.set_text_color(*_BODY)
    pdf.ln(5)

    pdf.set_font(_HDR_FONT, "B", 9)
    pdf.set_text_color(*_TEAL)
    summary = (
        f"Members: {len(rows)}   |   Combined balance: {total_balance:.8f} BTC   |   "
        f"Combined tx count: {int(total_tx_count)}   |   Sanctioned members: {sanctioned_count}"
    )
    pdf.cell(0, 7, text=_safe(summary), new_x="LMARGIN", new_y="NEXT")
    if sanctioned_count:
        pdf.set_text_color(180, 0, 0)
        pdf.cell(0, 6, text="[!] one or more members are on the OFAC SDN list", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_BODY)
    pdf.ln(3)

    pdf.set_font(_MONO_FONT, "", 8)
    with pdf.table(col_widths=(70, 25, 20, 25, 25, 60)) as table:
        header_row = table.row()
        for col in _CLUSTER_TABLE_COLUMNS:
            header_row.cell(col.replace("_", " ").title())
        for row in rows:
            table_row = table.row()
            for col in _CLUSTER_TABLE_COLUMNS:
                table_row.cell(_safe(str(row.get(col, ""))))

    dest = _resolve_path(f"cluster-{cluster_id}", out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dest))
    return dest
