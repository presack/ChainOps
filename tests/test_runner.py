from runner import render_query_banner


def test_render_query_banner_includes_target_and_marker():
    banner = render_query_banner("1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a", use_color=False)
    assert "QUERY START" in banner
    assert "1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a" in banner


def test_render_query_banner_no_ansi_codes_when_color_disabled():
    banner = render_query_banner("addr", use_color=False)
    assert "\x1b[" not in banner


def test_render_query_banner_has_ansi_codes_when_color_enabled():
    banner = render_query_banner("addr", use_color=True)
    assert "\x1b[" in banner
