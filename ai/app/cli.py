"""작성: rootkit · 2026-10-23. Run from ai/: python -m app.cli --help."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .errors import DomainError
from .knowledge import read_jsonl
from .service import Service
from .storage import Storage


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="rootkit immutable dataset and reviewed catalog administration")
    root.add_argument("--db", help="SQLite file (defaults to AI_DB_PATH or data/rootkit.sqlite3)")
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("import", "append", "replace"):
        item = commands.add_parser(command, help={"import": "Create a staged dataset revision", "append": "Stage a revision adding documents", "replace": "Import, extract, generate, review and atomically activate"}[command])
        item.add_argument("--dataset", required=True)
        item.add_argument("--file", required=True)
    terms = commands.add_parser("terms").add_subparsers(dest="action", required=True)
    for command in ("extract", "list", "approve"):
        item = terms.add_parser(command)
        item.add_argument("--dataset", required=True)
        item.add_argument("--version", required=True, type=int)
        if command == "approve":
            item.add_argument("--term-id", required=True)
            item.add_argument("--alias", action="append", default=[])
    catalogs = commands.add_parser("catalog").add_subparsers(dest="action", required=True)
    generate = catalogs.add_parser("generate")
    generate.add_argument("--dataset", required=True)
    generate.add_argument("--version", required=True, type=int)
    imported = catalogs.add_parser("import", help="Stage an authored catalog JSON for independent AI review")
    imported.add_argument("--dataset", required=True)
    imported.add_argument("--version", required=True, type=int)
    imported.add_argument("--file", required=True)
    for command in ("review", "activate", "show"):
        catalogs.add_parser(command).add_argument("--catalog", required=True)
    exports = commands.add_parser("reviews").add_subparsers(dest="action", required=True)
    exports.add_parser("export").add_argument("--output", required=True)
    commands.add_parser("status")
    return root


def main(argv: list[str] | None = None, service: Service | None = None) -> int:
    args = parser().parse_args(argv)
    service = service or Service(Storage(args.db))
    try:
        if args.command in {"import", "append", "replace"}:
            result = service.import_dataset(args.dataset, read_jsonl(args.file), mode="append" if args.command == "append" else "replace")
            if args.command == "replace":
                service.extract_knowledge(args.dataset, result["version"])
                catalog = service.generate_catalog(args.dataset, result["version"])
                service.review_catalog(catalog["catalog_id"])
                result = service.activate_catalog(catalog["catalog_id"])
        elif args.command == "terms":
            if args.action == "extract":
                result = service.extract_knowledge(args.dataset, args.version)
            elif args.action == "approve":
                result = service.approve_term(args.dataset, args.version, args.term_id, args.alias)
            else:
                result = service._dataset(args.dataset, args.version)["knowledge"]
        elif args.command == "catalog":
            if args.action == "generate":
                result = service.generate_catalog(args.dataset, args.version)
            elif args.action == "import":
                path = Path(args.file)
                if path.suffix.lower() != ".json":
                    raise DomainError("Catalog import requires a UTF-8 .json file")
                proposal = json.loads(path.read_text(encoding="utf-8-sig"))
                result = service.import_catalog(args.dataset, args.version, proposal)
            elif args.action == "review":
                result = service.review_catalog(args.catalog)
            elif args.action == "activate":
                result = service.activate_catalog(args.catalog)
            else:
                status, snapshot = service._catalog(args.catalog)
                result = {"catalog_id": args.catalog, "status": status, "snapshot": snapshot}
        elif args.command == "reviews":
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(service.review_export(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = {"output": str(output)}
        else:
            export = service.review_export()
            result = {"active_catalog_id": export["active_catalog_id"],
                      "datasets": [{key: value for key, value in dataset.items() if key not in {"documents", "knowledge"}}
                                   for dataset in export["datasets"]],
                      "catalogs": [{"catalog_id": catalog["catalog_id"], "status": catalog["status"]} for catalog in export["catalogs"]]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (DomainError, ValidationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        service.storage.event("cli", args.command, "failed", {"reason": str(exc), "code": getattr(exc, "code", "invalid_input")})
        print(json.dumps({"error": str(exc), "code": getattr(exc, "code", "invalid_input")}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
