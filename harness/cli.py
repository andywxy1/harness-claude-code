"""CLI entry point for Harness Claude."""

import argparse
import sys
from pathlib import Path

from harness.orchestrator import run_project


def main():
    parser = argparse.ArgumentParser(
        prog="harness-claude",
        description="Harness Claude — Generator-Evaluator orchestration for Claude Code",
    )
    parser.add_argument(
        "prompt",
        help="Project description — what you want to build",
    )
    parser.add_argument(
        "-w", "--workspace",
        default=None,
        help="Path to the project workspace directory (default: ./workspace)",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Disable the web UI (console-only mode)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8420,
        help="Port for the web UI (default: 8420)",
    )

    args = parser.parse_args()

    workspace = args.workspace
    if workspace is None:
        workspace = str(Path.cwd() / "workspace")

    try:
        run_project(
            args.prompt,
            workspace,
            web=not args.no_web,
            port=args.port,
        )
    except KeyboardInterrupt:
        print("\n\n[Harness] Interrupted by user. Progress has been git-committed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
