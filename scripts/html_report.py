"""Convert the generated Markdown report into a self-contained HTML document."""

from __future__ import annotations

import base64
import html
import mimetypes
import re
from pathlib import Path

from markdown_it import MarkdownIt


IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _embed_images(markdown: str, base_directory: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        alt_text, relative_path = match.groups()
        image_path = (base_directory / relative_path).resolve()
        if not image_path.is_file():
            return match.group(0)
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"![{alt_text}](data:{mime_type};base64,{encoded})"

    return IMAGE_PATTERN.sub(replace, markdown)


def build_self_contained_html(
    markdown: str,
    base_directory: Path,
    title: str,
) -> str:
    embedded_markdown = _embed_images(markdown, base_directory)
    renderer = MarkdownIt("commonmark", {"html": False}).enable("table")
    body = renderer.render(embedded_markdown)
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172033;
      --muted: #637083;
      --line: #dbe2ea;
      --panel: #ffffff;
      --soft: #f4f7fb;
      --accent: #185adb;
      --positive: #0d7a50;
      --risk: #b33a3a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #edf2f7;
      color: var(--ink);
      font-family: "Yu Gothic UI", "Hiragino Kaku Gothic ProN", Meiryo, sans-serif;
      line-height: 1.75;
    }}
    main {{
      width: min(1180px, calc(100% - 32px));
      margin: 32px auto 64px;
      padding: clamp(24px, 5vw, 64px);
      background: var(--panel);
      border-radius: 20px;
      box-shadow: 0 18px 50px rgba(27, 45, 75, .10);
    }}
    h1 {{
      margin-top: 0;
      padding-bottom: 18px;
      border-bottom: 3px solid var(--accent);
      font-size: clamp(1.8rem, 4vw, 2.8rem);
      line-height: 1.3;
    }}
    h2 {{
      margin-top: 54px;
      padding: 12px 16px;
      border-left: 6px solid var(--accent);
      background: var(--soft);
      border-radius: 0 10px 10px 0;
      font-size: 1.45rem;
    }}
    h3 {{ margin-top: 32px; font-size: 1.15rem; }}
    h3:nth-of-type(1) {{ color: var(--positive); }}
    h3:nth-of-type(2) {{ color: var(--risk); }}
    p, li {{ max-width: 92ch; }}
    code {{
      padding: 2px 6px;
      background: #eef2f7;
      border-radius: 5px;
      font-family: Consolas, monospace;
    }}
    strong {{
      display: inline-block;
      padding: 8px 14px;
      color: #fff;
      background: var(--accent);
      border-radius: 999px;
    }}
    table {{
      width: 100%;
      margin: 18px 0 32px;
      border-collapse: separate;
      border-spacing: 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 12px;
      font-size: .92rem;
    }}
    thead th {{
      position: sticky;
      top: 0;
      z-index: 1;
      padding: 11px 12px;
      color: #fff;
      background: #263b61;
      text-align: left;
      white-space: nowrap;
    }}
    tbody td {{
      padding: 10px 12px;
      border-top: 1px solid var(--line);
      vertical-align: top;
    }}
    tbody tr:nth-child(even) {{ background: #f8fafc; }}
    tbody tr:hover {{ background: #edf5ff; }}
    img {{
      display: block;
      width: 100%;
      height: auto;
      margin: 20px auto 34px;
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 8px 24px rgba(24, 38, 60, .08);
    }}
    ul {{ padding-left: 1.35rem; }}
    blockquote {{
      margin: 20px 0;
      padding: 14px 18px;
      border-left: 4px solid var(--accent);
      background: var(--soft);
    }}
    .notice {{
      margin-bottom: 28px;
      padding: 12px 16px;
      color: var(--muted);
      background: var(--soft);
      border-radius: 10px;
      font-size: .9rem;
    }}
    @media (max-width: 720px) {{
      main {{ width: 100%; margin: 0; border-radius: 0; padding: 20px; }}
      table {{ display: block; overflow-x: auto; }}
      h2 {{ margin-top: 38px; }}
    }}
    @media print {{
      body {{ background: #fff; }}
      main {{ width: 100%; margin: 0; padding: 0; box-shadow: none; }}
      h2 {{ break-after: avoid; }}
      table, img {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="notice">自己完結型HTMLレポート / グラフ埋め込み済み / DB読み取り専用</div>
    {body}
  </main>
</body>
</html>
"""

