"""URL parsing, timestamp formatting, and the two bidirectional-component traps."""

import pytest

from volley import video


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90s",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/v/dQw4w9WgXcQ",
        "http://youtu.be/dQw4w9WgXcQ?t=12",
        "youtu.be/dQw4w9WgXcQ",
        "  https://youtu.be/dQw4w9WgXcQ  ",
        "dQw4w9WgXcQ",
    ],
)
def test_parse_youtube_id(url):
    assert video.parse_youtube_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url", ["", None, "https://vimeo.com/123456", "not a url", "https://youtu.be/short"]
)
def test_parse_youtube_id_rejects(url):
    assert video.parse_youtube_id(url) is None


def test_the_panel_is_declared_against_the_real_frontend():
    assert (video.FRONTEND_DIR / "index.html").exists()
    html = (video.FRONTEND_DIR / "index.html").read_text()

    # One-way: it plays, and tells Python nothing.
    assert "setComponentValue" not in html
    # It must still survive a rerun - the whole reason this is a component
    # rather than an st.video call - so the src is only touched when the id
    # actually changes.
    assert "videoId === current" in html
    assert "componentReady" in html

    # No YouTube IFrame API. It only existed to read the player clock, which
    # nothing needs now, and it was the part that could fail to re-initialise
    # after Streamlit rebuilt the frame and leave the panel blank for good.
    for fragile in ("iframe_api", "onYouTubeIframeAPIReady", "YT.Player"):
        assert fragile not in html, f"{fragile} is back"
    assert "youtube.com/embed/" in html
