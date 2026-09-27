"""YouTube panel: URL parsing, timestamp formatting, and the Streamlit component.

The panel is a custom component rather than `st.video` or a plain iframe
because Streamlit re-executes the script on every interaction. Streamlit
re-posts args into an existing component iframe instead of recreating it, so
playback survives reruns - a video that restarted on every recorded kill would
be worse than no video at all.

No build step is involved: `declare_component(path=...)` serves a hand-written
`frontend/index.html`.
"""

from __future__ import annotations

import re
from pathlib import Path

import streamlit.components.v1 as components

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

_ID = r"[A-Za-z0-9_-]{11}"
_URL_PATTERNS = [
    re.compile(rf"youtu\.be/({_ID})"),
    re.compile(rf"youtube\.com/watch\?(?:[^ ]*&)?v=({_ID})"),
    re.compile(rf"youtube\.com/embed/({_ID})"),
    re.compile(rf"youtube\.com/live/({_ID})"),
    re.compile(rf"youtube\.com/shorts/({_ID})"),
    re.compile(rf"youtube\.com/v/({_ID})"),
]
_BARE_ID = re.compile(rf"^{_ID}$")


def parse_youtube_id(url: str | None) -> str | None:
    """Pull the video id out of any common YouTube URL shape, or None."""
    if not url:
        return None
    text = str(url).strip()
    if _BARE_ID.match(text):
        return text
    for pattern in _URL_PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group(1)
    return None


_COMPONENT = None


def _component():
    """Declared once and cached - re-declaring the same name is not free."""
    global _COMPONENT
    if _COMPONENT is None:
        _COMPONENT = components.declare_component("volley_video", path=str(FRONTEND_DIR))
    return _COMPONENT


def video_panel(video_id: str | None, height: int = 560, max_height: int = 2000,
                key: str = "video_panel"):
    """Render the player.

    `max_height` caps it so a full-width container does not produce a
    thousand-pixel-tall video; the default is effectively no cap.
    """
    return _component()(
        video_id=video_id or "",
        height=int(height),
        max_height=int(max_height),
        key=key,
        default=None,
    )
