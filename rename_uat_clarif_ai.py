"""Rename the existing app in place without replacing feature files.

Put this script in the project root and run it using the project's Python.
"""
from pathlib import Path
import re


def main():
    root = Path(__file__).resolve().parent
    static = root / "static"
    if not static.is_dir() or not (root / "app" / "main.py").is_file():
        raise SystemExit("Extract this script into the project root containing static and app, then run it again.")
    files = {root / "app" / "main.py", *root.glob("*.html")}
    files.update(path for path in static.rglob("*") if path.is_file() and path.suffix.lower() in {".html", ".htm", ".js"})
    old_name = re.compile(r"UAT(?:,\s*|\s+)Untangled", re.IGNORECASE)
    count = 0
    for path in sorted(files):
        text = path.read_bytes().decode("utf-8-sig")
        renamed, matches = old_name.subn("UAT Clarif-AI", text)
        if matches:
            path.write_bytes(renamed.encode("utf-8"))
            print(f"Updated {path.relative_to(root)}")
            count += 1
    print(f"Updated {count} files. Restart Uvicorn, then press Ctrl+F5 in your browser.")
    print("Brand: UAT Clarif-AI. Page headings such as Review queue keep their existing meaning.")


if __name__ == "__main__":
    main()
