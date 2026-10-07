# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structure of the static dashboard page (no browser, no server).

The safety and scope notes live in a modal dialog that the page shows before it
connects; the FHIR resource viewer takes their former place; device details sit
in the latest-reading card.
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


def test_disclaimers_are_in_the_welcome_dialog_with_an_acknowledge_button() -> None:
    """Both warnings are inside the modal, which the user closes with "I understand"."""
    outline = _outline()
    dialog_text = _text_inside(outline, "welcome-dialog")

    assert "unauthenticated" in dialog_text
    assert "not a medical device" in dialog_text
    assert "hipaa" in dialog_text
    assert "welcome-dialog" in outline.ancestors["welcome-ack"]
    assert "i understand" in _text_inside(outline, "welcome-ack")


def test_page_connects_only_after_the_notes_are_acknowledged() -> None:
    """``init`` hands the connection step to the welcome gate instead of calling it directly."""
    script = (_STATIC / "app.js").read_text(encoding="utf-8")
    init = script[script.index("function init()") :]
    init = init[: init.index("\n  }\n")]

    assert "requireWelcome(checkAuthRequired)" in init
    assert "checkAuthRequired();" not in init


def test_fhir_viewer_replaces_the_notice_card() -> None:
    """The viewer is the last card in ``main``; the old notice card is gone."""
    outline = _outline()

    for element_id in ("fhir-card", "fhir-json", "fhir-pause", "fhir-trail", "fhir-recent"):
        assert element_id in outline.ancestors, element_id
    assert "<main>" in outline.ancestors["fhir-card"]
    assert "notice-heading" not in outline.ancestors
    script = (_STATIC / "app.js").read_text(encoding="utf-8")
    for element_id in ("fhir-json", "fhir-pause", "fhir-trail", "fhir-recent"):
        assert f'"{element_id}"' in script, element_id


def test_device_details_sit_in_the_latest_reading_card() -> None:
    """Device details are rendered under the heart rate, from the FHIR Device resource."""
    outline = _outline()
    script = (_STATIC / "app.js").read_text(encoding="utf-8")

    assert "reading-card" in outline.ancestors["hr-value"]
    assert "reading-card" in outline.ancestors["device-props"]
    assert '"device-props"' in script
    assert '"/fhir/"' in script
