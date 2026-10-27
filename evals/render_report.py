import argparse
import sys
from pathlib import Path

from evals.html_report import render_html
from evals.report import render
from evals.results import BakeoffResults

RESULTS_NAME = "bakeoff.json"


def write_reports(results: BakeoffResults, out_dir: Path) -> list[Path]:
    """Writes the JSON first, so a renderer crash still leaves the paid-for results on disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / RESULTS_NAME
    results.save(results_path)
    markdown_path = out_dir / "bakeoff.md"
    markdown_path.write_text(render(results))
    html_path = out_dir / "bakeoff.html"
    html_path.write_text(render_html(results))
    return [results_path, markdown_path, html_path]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild bakeoff.md and bakeoff.html from a saved bakeoff.json without live calls."
    )
    parser.add_argument("results", type=Path, help="path to bakeoff.json")
    args = parser.parse_args()
    results = BakeoffResults.load(args.results)
    for path in write_reports(results, args.results.parent):
        print(f"written {path}", file=sys.stderr)
    return 0 if results.passed else 1


if __name__ == "__main__":
    sys.exit(main())
