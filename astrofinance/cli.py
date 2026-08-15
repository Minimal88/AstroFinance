import argparse
import sys

from astrofinance import db, pull_service
from astrofinance.sheets_client import SheetError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="astrofinance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create the SQLite database and schema")

    pull = subparsers.add_parser("pull", help="Mirror the Google Sheet into SQLite")
    pull.add_argument(
        "--rebuild", action="store_true", help="Clear local rows and reload from scratch"
    )
    pull.add_argument(
        "--no-prune", action="store_true", help="Keep local rows that are gone from the Sheet"
    )

    args = parser.parse_args(argv or sys.argv[1:])

    if args.command == "init-db":
        print(f"Database ready at {db.init_db()}")
        return 0

    try:
        result = pull_service.run_pull(rebuild=args.rebuild, prune=not args.no_prune)
    except SheetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"{result.new} new, {result.updated} updated, "
        f"{result.pruned} pruned, {len(result.errors)} errors"
    )
    for error in result.errors:
        print(f"  {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
