from __future__ import annotations

import argparse
import re
from pathlib import Path


def _guess_title(md_text: str, fallback: str) -> str:
    # First ATX heading (# Title)
    for line in md_text.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return fallback


def _file_url(path: Path) -> str:
    # pathlib handles Windows drive letters correctly.
    return path.resolve().as_uri()


def render_markdown_to_html(
    *,
    input_path: Path,
    output_path: Path,
    title: str | None,
    base_href: str | None,
    css_files: list[str],
) -> None:
    md_text = input_path.read_text(encoding="utf-8")

    if title is None:
        title = _guess_title(md_text, input_path.stem)

    try:
        import markdown  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Missing Python package 'Markdown'. Install it into the repo venv: "
            "./scripts/update-docs.ps1 will auto-install it, or run: "
            ".venv\\Scripts\\python.exe -m pip install Markdown"
        ) from exc

    body_html = markdown.markdown(
        md_text,
        output_format="html",
        extensions=[
            "fenced_code",
            "tables",
            "sane_lists",
            "smarty",
            "toc",
        ],
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    css_links = "\n".join(
        f'    <link rel="stylesheet" href="{href}">' for href in css_files if href
    )

    base_tag = f'    <base href="{base_href}">' if base_href else ""

    # Minimal built-in styling; external css can override.
    built_in_css = """
    :root { color-scheme: light dark; }
    body { max-width: 920px; margin: 40px auto; padding: 0 16px; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; line-height: 1.55; }
    code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace; }
    pre { padding: 12px 14px; overflow-x: auto; border: 1px solid rgba(127,127,127,.35); border-radius: 8px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid rgba(127,127,127,.35); padding: 6px 8px; }
    blockquote { margin: 0; padding-left: 14px; border-left: 4px solid rgba(127,127,127,.35); }
    img { max-width: 100%; height: auto; }
    """.strip()

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>{title}</title>
{base_tag}
{css_links}
    <style>{built_in_css}</style>
</head>
<body>
{body_html}
</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--title", default=None)
    parser.add_argument("--base-href", default=None)
    parser.add_argument("--css", action="append", default=[])

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    base_href = args.base_href
    if base_href == "__AUTO__":
        base_href = _file_url(input_path.parent) + "/"

    render_markdown_to_html(
        input_path=input_path,
        output_path=output_path,
        title=args.title,
        base_href=base_href,
        css_files=args.css or [],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
