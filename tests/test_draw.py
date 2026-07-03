import xml.etree.ElementTree as ET
from unittest.mock import patch

from draw import build_drawio_xml, save_drawio_file

SEED = "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a"

NODES = {SEED: {"depth": 0}, "addrB": {"depth": 1}, "addrC": {"depth": 1}}
EDGES = [
    {"txid": "t1", "from": SEED, "to": "addrB", "value_sats": 100000},
    {"txid": "t1", "from": SEED, "to": "addrC", "value_sats": 200000},
]


def test_build_drawio_xml_is_well_formed():
    xml_str = build_drawio_xml(NODES, EDGES, seed=SEED)
    root = ET.fromstring(xml_str)  # raises if malformed
    assert root.tag == "mxGraphModel"


def test_build_drawio_xml_has_one_vertex_per_node():
    xml_str = build_drawio_xml(NODES, EDGES, seed=SEED)
    root = ET.fromstring(xml_str)
    vertices = root.findall(".//mxCell[@vertex='1']")
    assert len(vertices) == 3


def test_build_drawio_xml_has_one_edge_cell_per_edge():
    xml_str = build_drawio_xml(NODES, EDGES, seed=SEED)
    root = ET.fromstring(xml_str)
    edge_cells = root.findall(".//mxCell[@edge='1']")
    assert len(edge_cells) == 2


def test_seed_node_is_labeled_and_styled_distinctly():
    xml_str = build_drawio_xml(NODES, EDGES, seed=SEED)
    root = ET.fromstring(xml_str)
    seed_cell = next(c for c in root.findall(".//mxCell[@vertex='1']") if "(seed)" in c.get("value", ""))
    assert "strokeWidth=3" in seed_cell.get("style", "")


def test_edge_value_shows_btc_amount():
    xml_str = build_drawio_xml(NODES, EDGES, seed=SEED)
    root = ET.fromstring(xml_str)
    values = {c.get("value") for c in root.findall(".//mxCell[@edge='1']")}
    assert "0.00100000 BTC" in values
    assert "0.00200000 BTC" in values


def test_contract_node_renders_as_rectangle_not_rounded():
    nodes = {SEED: {"depth": 0}, "addrB": {"depth": 1, "is_contract": True}}
    xml_str = build_drawio_xml(nodes, [], seed=SEED)
    root = ET.fromstring(xml_str)

    seed_cell = next(c for c in root.findall(".//mxCell[@vertex='1']") if "(seed)" in c.get("value", ""))
    contract_cell = next(c for c in root.findall(".//mxCell[@vertex='1']") if "addrB" in c.get("value", ""))

    assert "rounded=1" in seed_cell.get("style", "")
    assert "rounded=0" in contract_cell.get("style", "")
    assert "[contract]" in contract_cell.get("value", "")


def test_sanctioned_node_renders_red_regardless_of_depth():
    nodes = {SEED: {"depth": 0}, "addrB": {"depth": 1, "sanctioned": True}}
    xml_str = build_drawio_xml(nodes, [], seed=SEED)
    root = ET.fromstring(xml_str)

    sanctioned_cell = next(c for c in root.findall(".//mxCell[@vertex='1']") if "addrB" in c.get("value", ""))

    assert "fillColor=#ff0000" in sanctioned_cell.get("style", "")
    assert "[!] SANCTIONED" in sanctioned_cell.get("value", "")


def test_scam_flagged_node_renders_orange():
    nodes = {SEED: {"depth": 0}, "addrB": {"depth": 1, "scam_flagged": True}}
    xml_str = build_drawio_xml(nodes, [], seed=SEED)
    root = ET.fromstring(xml_str)

    scam_cell = next(c for c in root.findall(".//mxCell[@vertex='1']") if "addrB" in c.get("value", ""))

    assert "fillColor=#ffa500" in scam_cell.get("style", "")
    assert "[!] SCAM-LISTED" in scam_cell.get("value", "")


def test_sanctioned_overrides_scam_flagged_color():
    nodes = {SEED: {"depth": 0}, "addrB": {"depth": 1, "scam_flagged": True, "sanctioned": True}}
    xml_str = build_drawio_xml(nodes, [], seed=SEED)
    root = ET.fromstring(xml_str)

    cell = next(c for c in root.findall(".//mxCell[@vertex='1']") if "addrB" in c.get("value", ""))

    assert "fillColor=#ff0000" in cell.get("style", "")  # sanctions take priority over the scam-list color


def test_edge_value_shows_token_amount_and_symbol():
    token_nodes = {SEED: {"depth": 0}, "TNeighbor": {"depth": 1}}
    token_edges = [{"txid": "t1", "from": SEED, "to": "TNeighbor", "value": 12.5, "symbol": "USDT"}]

    xml_str = build_drawio_xml(token_nodes, token_edges, seed=SEED)
    root = ET.fromstring(xml_str)
    values = {c.get("value") for c in root.findall(".//mxCell[@edge='1']")}
    assert "12.500000 USDT" in values


def test_edge_referencing_missing_node_is_skipped():
    edges_with_dangling = EDGES + [{"txid": "t2", "from": SEED, "to": "unknown_addr", "value_sats": 1}]
    xml_str = build_drawio_xml(NODES, edges_with_dangling, seed=SEED)
    root = ET.fromstring(xml_str)
    edge_cells = root.findall(".//mxCell[@edge='1']")
    assert len(edge_cells) == 2  # dangling edge dropped, not 3


def test_long_address_label_is_truncated():
    xml_str = build_drawio_xml(NODES, EDGES, seed=SEED)
    root = ET.fromstring(xml_str)
    seed_cell = next(c for c in root.findall(".//mxCell[@vertex='1']") if "seed" in c.get("value", ""))
    assert "..." in seed_cell.get("value", "")
    assert len(seed_cell.get("value", "")) < len(SEED)


def test_empty_graph_still_produces_valid_xml():
    xml_str = build_drawio_xml({}, [])
    root = ET.fromstring(xml_str)
    assert root.findall(".//mxCell[@vertex='1']") == []


def test_save_drawio_file_writes_to_given_path(tmp_path):
    out_path = str(tmp_path / "test.drawio")
    result_path = save_drawio_file(NODES, EDGES, seed=SEED, out_path=out_path)

    assert result_path == out_path
    content = (tmp_path / "test.drawio").read_text()
    assert "mxGraphModel" in content


@patch("draw.Path.home")
def test_save_drawio_file_default_path_uses_downloads_and_timestamp(mock_home, tmp_path):
    mock_home.return_value = tmp_path
    result_path = save_drawio_file(NODES, EDGES, seed=SEED)

    assert result_path.startswith(str(tmp_path / "Downloads"))
    assert result_path.endswith(".drawio")
    assert "chainops-map-" in result_path
