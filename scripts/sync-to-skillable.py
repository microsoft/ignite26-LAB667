"""Generate the legacy `skillable.md` and `index.html` workshop exports.

The numbered Guided Mode markdown files live in `player/guided/`. This script
regenerates the two legacy index files in `player/` without publishing them.
The original deployment workflows are retained, inactive, under
`infra/legacy-workflows/`.

- `skillable.md`: page-separated list of `!INSTRUCTIONS[<title>](<url>)`
   entries, one per workshop step, used to import the workshop into
   Skillable.
- `index.html`: simple landing page linking each step, served at the root
   of the Static Web App.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDED_DIR = ROOT / "player" / "guided"
OUTPUT_DIR = ROOT / "player"
SKILLABLE_FILE = "skillable.md"
INDEX_FILE = "index.html"
BASE_URL = "https://raw.githubusercontent.com/GlobalAICommunity/lab530-skillable/refs/heads/main/"


def extract_title(md_path: Path) -> str:
    """Return the first H1 heading from a markdown file, or the filename stem."""
    with md_path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    return md_path.stem


def write_skillable(entries: list[tuple[str, str]]) -> Path:
    base = BASE_URL if BASE_URL.endswith("/") else BASE_URL + "/"
    content = "\n===\n".join(
        f"!INSTRUCTIONS[{title}]({base}{name})" for name, title in entries
    ) + "\n"
    path = OUTPUT_DIR / SKILLABLE_FILE
    path.write_text(content, encoding="utf-8")
    return path


def write_index(entries: list[tuple[str, str]]) -> Path:
    items = "\n".join(
        f'    <li><a href="{name}">{title}</a></li>' for name, title in entries
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Lost in the City — Workshop</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }}
    li {{ margin: 0.25rem 0; }}
  </style>
</head>
<body>
  <h1>Lost in the City — Workshop</h1>
  <p>Workshop instructions:</p>
  <ul>
{items}
  </ul>
</body>
</html>
"""
    path = OUTPUT_DIR / INDEX_FILE
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    md_files = sorted(GUIDED_DIR.glob("[0-9][0-9]_*.md"))
    if not md_files:
        raise SystemExit(f"No numbered Guided Mode chapters found in {GUIDED_DIR}.")

    entries = [(f"guided/{md.name}", extract_title(md)) for md in md_files]

    skillable_path = write_skillable(entries)
    print(f"Wrote {skillable_path}")

    index_path = write_index(entries)
    print(f"Wrote {index_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
