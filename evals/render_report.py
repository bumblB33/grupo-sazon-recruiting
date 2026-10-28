import argparse
import sys
from pathlib import Path

from evals.html_report import render_html
from evals.results import BakeoffResults, IncompatibleResultsError

RESULTS_NAME = "bakeoff.json"
REPORT_NAME = "bakeoff.html"


def write_reports(results: BakeoffResults, out_dir: Path) -> list[Path]:
    """Writes the JSON first, so a renderer crash still leaves the paid-for results on disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / RESULTS_NAME
    results.save(results_path)
    html_path = out_dir / REPORT_NAME
    html_path.write_text(render_html(results))
    return [results_path, html_path]


def main() -> int:
    """Exit status reports the rendering, not the bake-off verdict, which the report shows."""
    parser = argparse.ArgumentParser(
        description="Rebuild bakeoff.html from a saved bakeoff.json without live calls."
    )
    parser.add_argument("results", type=Path, help="path to bakeoff.json")
    args = parser.parse_args()
    try:
        results = BakeoffResults.load(args.results)
    except IncompatibleResultsError as exc:
        parser.error(str(exc))
    for path in write_reports(results, args.results.parent):
        print(f"written {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
