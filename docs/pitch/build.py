"""Builds index.html, a self-contained viewer for the pitch deck, from deck.json and slides/.

    python3 docs/pitch/build.py

The slide files use the 1920×1080 slide format of the Slides artifact the deck was made in; this
viewer only adds the CSS needed to show them in a browser (fonts, scaling, the x-shape kinds). On a
narrow screen (a phone) the speaker notes show as text under each slide instead of over it, where
they would be too small to read.
"""

import json
import re
from html import escape
from pathlib import Path

HERE = Path(__file__).parent

STYLE = """
* { box-sizing: border-box; }
html, body { margin: 0; background: #1b1d21; font-family: 'Libre Franklin', Arial, sans-serif; }
header { color: #e6e8eb; padding: 24px 32px; display: flex; gap: 16px; align-items: baseline;
  flex-wrap: wrap; }
header h1 { margin: 0; font-size: 22px; }
header span { color: #9aa3ad; font-size: 15px; }
header label { margin-left: auto; color: #c9ced4; font-size: 15px; }
.frame { margin: 0 auto 32px; overflow: hidden; border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0,0,0,.4); }
.slide { width: 1920px; height: 1080px; transform-origin: top left; }
section { position: relative; width: 1920px; height: 1080px; overflow: hidden; }
section h1, section h2, section h3, section p { margin: 0; }
section ul { margin: 0; padding-left: 1.2em; }
section table { border-collapse: collapse; width: 100%; overflow: hidden; }
section th, section td { text-align: left; padding: 18px 28px; border-bottom: 1px solid rgba(0,0,0,.08); }
section aside { display: none; }
body.notes section aside { display: block; position: absolute; left: 0; right: 0; bottom: 0;
  background: rgba(20,24,29,.92); color: #f4f6f8; font-size: 26px; line-height: 1.4; padding: 24px 40px; }
.note { display: none; max-width: 1600px; margin: -16px auto 32px; color: #c9ced4; font-size: 15px;
  line-height: 1.5; }
@media (max-width: 900px) {
  header { padding: 16px; }
  header label { margin-left: 0; }
  .frame { margin-bottom: 20px; border-radius: 4px; }
  body.notes section aside { display: none; }
  body.notes .note { display: block; padding: 0 16px; margin-top: -8px; }
}
x-shape { display: block; flex: none; }
x-shape[kind="ellipse"] { border-radius: 50%; }
x-shape[kind="arrow-right"] { clip-path: polygon(0 30%, 60% 30%, 60% 0, 100% 50%, 60% 100%, 60% 70%, 0 70%); }
x-shape[kind="arrow-left"] { clip-path: polygon(100% 30%, 40% 30%, 40% 0, 0 50%, 40% 100%, 40% 70%, 100% 70%); }
x-shape[kind="arrow-down"] { clip-path: polygon(30% 0, 70% 0, 70% 60%, 100% 60%, 50% 100%, 0 60%, 30% 60%); }
x-shape[kind="arrow-up"] { clip-path: polygon(30% 100%, 70% 100%, 70% 40%, 100% 40%, 50% 0, 0 40%, 30% 40%); }
"""

SCRIPT = """
function fit() {
  const gutter = window.innerWidth <= 900 ? 32 : 64;
  const width = Math.min(window.innerWidth - gutter, 1600);
  const scale = width / 1920;
  document.querySelectorAll('.frame').forEach((f) => {
    f.style.width = width + 'px';
    f.style.height = 1080 * scale + 'px';
    f.firstElementChild.style.transform = 'scale(' + scale + ')';
  });
}
window.addEventListener('resize', fit);
fit();
document.getElementById('notes').addEventListener('change', (e) => {
  document.body.classList.toggle('notes', e.target.checked);
});
"""


def _slide(html: str) -> str:
    """One slide in its frame, followed by its speaker notes for narrow screens."""
    notes = re.search(r"<aside>(.*?)</aside>", html, re.S)
    note = f'<div class="note">{notes.group(1)}</div>\n' if notes else ""
    return f'<div class="frame"><div class="slide">\n{html}</div></div>\n{note}'


def build() -> str:
    deck = json.loads((HERE / "deck.json").read_text())
    fonts = "".join(
        f'<link rel="stylesheet" href="{escape(face["href"])}">\n'
        for face in deck["faces"].values()
        if "href" in face
    )
    slides = "".join(_slide((HERE / "slides" / f"{sid}.html").read_text()) for sid in deck["order"])
    title = escape(deck["title"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{fonts}<style>{STYLE}</style>
</head>
<body>
<header><h1>{title}</h1><span>{len(deck["order"])} slides · generated from docs/pitch/slides by build.py</span>
<label><input type="checkbox" id="notes"> Speaker notes</label></header>
{slides}<script>{SCRIPT}</script>
</body>
</html>
"""


if __name__ == "__main__":
    (HERE / "index.html").write_text(build())
    print(f"wrote {HERE / 'index.html'}")
