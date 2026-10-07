# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structure of the static dashboard page (no browser, no server).

The page has two screens. The start screen carries the safety and scope notes
and the access token; nothing connects until "I understand". The app screen has
a Home button, the readings on the left with the device details under the heart
rate, and the FHIR resource viewer on the right.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "src" / "vitals_on_fhir" / "dashboard" / "static"


class _Outline(HTMLParser):
    """Record each element's id and the ids of the elements enclosing it."""

    _VOID = {"meta", "link", "input", "br", "img"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.ancestors: dict[str, list[str]] = {}
        self.text_by_ancestor: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id") or f"<{tag}>"
        self.ancestors.setdefault(element_id, list(self.stack))
        if tag not in self._VOID:
            self.stack.append(element_id)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self._VOID and self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        for element_id in self.stack:
            self.text_by_ancestor.setdefault(element_id, []).append(data)


def _outline() -> _Outline:
    parser = _Outline()
    parser.feed((_STATIC / "index.html").read_text(encoding="utf-8"))
    return parser


def _text_inside(outline: _Outline, element_id: str) -> str:
    return " ".join(" ".join(outline.text_by_ancestor.get(element_id, [])).split()).lower()


def _script() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def _function_body(script: str, name: str) -> str:
    body = script[script.index(f"function {name}(") :]
    return body[: body.index("\n  }\n")]


def test_start_screen_has_the_notes_and_the_token() -> None:
    """The warnings and the token field are on the start screen, before "I understand"."""
    outline = _outline()
    home_text = _text_inside(outline, "home-view")

    assert "unauthenticated" in home_text
    assert "not a medical device" in home_text
    assert "hipaa" in home_text
    for element_id in ("token-input", "connect-button", "connect-error", "demo-note"):
        assert "home-view" in outline.ancestors[element_id], element_id
    assert "i understand" in _text_inside(outline, "connect-button")


def test_app_screen_has_no_token_field_and_a_home_button() -> None:
    """The token is asked for only on the start screen; Home leads back to it."""
    outline = _outline()

    assert "app-view" not in outline.ancestors["token-input"]
    assert "app-view" in outline.ancestors["home-button"]
    assert "home" in _text_inside(outline, "home-button")
    assert "home-view" not in outline.ancestors["reading-card"]


def test_page_connects_only_from_the_start_screen() -> None:
    """``init`` opens no connection; submitting the start screen does, after a token check."""
    script = _script()
    init = _function_body(script, "init")
    on_submit = _function_body(script, "onSubmit")

    assert "openSocket" not in init
    assert "enterApp" not in init
    assert "checkToken(token)" in on_submit
    assert "openSocket(currentToken)" in _function_body(script, "enterApp")


def test_home_forgets_the_token_and_disconnects() -> None:
    """Home closes the socket and clears the token; the token is never stored."""
    script = _script()
    disconnect = _function_body(script, "disconnect")

    assert 'currentToken = "";' in disconnect
    assert "socket.close()" in disconnect
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    theme = (_STATIC / "theme.js").read_text(encoding="utf-8")
    assert "token" not in theme.lower()


def test_fhir_viewer_sits_beside_the_readings() -> None:
    """The viewer is in the right-hand column; the reading and chart are in the left."""
    outline = _outline()

    for element_id in ("fhir-card", "fhir-json", "fhir-pause", "fhir-trail", "fhir-recent"):
        assert "app-side" in outline.ancestors[element_id], element_id
    for element_id in ("reading-card", "hr-chart"):
        assert "app-main" in outline.ancestors[element_id], element_id
    script = _script()
    for element_id in ("fhir-json", "fhir-pause", "fhir-trail", "fhir-recent"):
        assert f'"{element_id}"' in script, element_id
    css = (_STATIC / "style.css").read_text(encoding="utf-8")
    assert "grid-template-columns: minmax(0, 5fr) minmax(0, 6fr)" in css


def test_device_details_sit_in_the_latest_reading_card() -> None:
    """Device details are rendered under the heart rate, from the FHIR Device resource."""
    outline = _outline()
    script = _script()

    assert "reading-card" in outline.ancestors["hr-value"]
    assert "reading-card" in outline.ancestors["device-props"]
    assert '"device-props"' in script
    assert '"/fhir/"' in script


def test_heart_rate_chart_is_a_scrolling_strip_with_10_second_ticks() -> None:
    """The chart is titled "Heart rate", scrolls sideways, and ticks every 10 s."""
    outline = _outline()
    script = _script()
    css = (_STATIC / "style.css").read_text(encoding="utf-8")

    assert _text_inside(outline, "chart-heading") == "heart rate"
    assert "CHART_TICK_S = 10;" in script
    assert 'sec + " s"' in script
    assert "CHART_WINDOW_MS" not in script
    assert ".chart-scroll {" in css
    assert "overflow-x: auto;" in css[css.index(".chart-scroll {") :]
    assert "app-main" in outline.ancestors["chart-latest"]


def test_logo_is_shipped_and_every_reference_resolves() -> None:
    """The page (start screen, app header, tab icon) and the README point at the shipped logo."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    readme = (_STATIC.parents[3] / "README.md").read_text(encoding="utf-8")

    assert (_STATIC / "logo.jpeg").is_file()
    assert html.count('src="logo.jpeg"') == 2
    assert 'rel="icon" href="logo.jpeg"' in html
    assert 'src="src/vitals_on_fhir/dashboard/static/logo.jpeg"' in readme


def test_toolbar_with_theme_switch_and_repo_link_is_on_both_screens() -> None:
    """The theme switch and the GitHub link sit outside both screens, so each shows them."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    toolbar = html[html.index('<nav class="toolbar"') : html.index("</nav>")]

    assert 'data-theme-choice="light"' in toolbar
    assert 'data-theme-choice="dark"' in toolbar
    assert 'href="https://github.com/soroushdty/vitals-on-fhir"' in toolbar
    assert 'target="_blank"' in toolbar
    assert 'rel="noopener noreferrer"' in toolbar
    assert html.index('<nav class="toolbar"') < html.index('id="home-view"')


def test_theme_script_runs_in_head_and_stores_only_the_theme() -> None:
    """``theme.js`` loads before the body is drawn and writes nothing but the theme name."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    theme = (_STATIC / "theme.js").read_text(encoding="utf-8")

    assert html.index('<script src="theme.js"></script>') < html.index("</head>")
    assert theme.count("setItem(") == 1
    assert "setItem(STORAGE_KEY, theme)" in theme
    assert "Storage" not in _script()  # app.js keeps nothing, the token included


def _tokens(block: str) -> set[str]:
    return {
        line.split(":")[0].strip() for line in block.splitlines() if line.strip().startswith("--")
    }


def test_dark_theme_defines_every_colour_token() -> None:
    """Both dark rules (system preference and explicit choice) cover every light token."""
    css = (_STATIC / "style.css").read_text(encoding="utf-8")

    def block(selector: str) -> str:
        start = css.index(selector)
        return css[start : css.index("}", start)]

    light = _tokens(block(":root {"))
    assert light
    assert _tokens(block(':root:not([data-theme="light"]) {')) == light
    assert _tokens(block(':root[data-theme="dark"] {')) == light
