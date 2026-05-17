from __future__ import annotations

import argparse

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone wet-lab personalization workbench")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the standalone workbench web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8015)
    serve.add_argument("--reload", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        uvicorn.run(
            "extensions.workbench.app:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0
    raise AssertionError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
