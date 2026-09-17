"""Isolated job executable. Exit 75 marks a transient ingestion failure."""
import argparse
import logging


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("analysis", "ingestion"))
    parser.add_argument("entity_id", type=int)
    parser.add_argument("user_id", type=int)
    args = parser.parse_args()
    from app.worker import _is_transient, _run_ingestion, _run_pipeline

    function = _run_pipeline if args.kind == "analysis" else _run_ingestion
    try:
        function(args.entity_id, args.user_id)
    except Exception as exc:
        logging.getLogger(__name__).exception("%s job %d failed", args.kind, args.entity_id)
        return 75 if _is_transient(exc) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
