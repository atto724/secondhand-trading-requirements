"""Check Black formatting sequentially without worker/cache subprocess dependencies."""

import sys
from pathlib import Path

import black

files = []
for argument in sys.argv[1:]:
    path = Path(argument)
    files.extend(path.rglob("*.py") if path.is_dir() else [path])
failures = []
for path in files:
    content = path.read_text(encoding="utf-8-sig")
    if black.format_str(content, mode=black.Mode(line_length=100)) != content:
        failures.append(str(path))
if failures:
    raise SystemExit("Black formatting differs: " + ", ".join(failures))
print(f"Black formatting: {len(files)} files passed")
