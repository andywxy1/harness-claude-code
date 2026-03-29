"""CLI entry point for Harness Claude."""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="harness-claude",
        description="Harness Claude — Generator-Evaluator orchestration for Claude Code",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Project description. If omitted, starts the web UI for interactive use.",
    )
    parser.add_argument(
        "-w", "--workspace",
        default=None,
        help="Path to the project workspace directory (default: ./workspace)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a crashed/stopped project from the workspace state",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Disable the web UI (console-only mode, requires prompt or --resume)",
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
        if args.resume:
            # Resume mode
            from harness.orchestrator import resume_project
            resume_project(workspace, web=not args.no_web, port=args.port)
        elif args.prompt is None:
            # No prompt — start web UI in standalone mode
            if args.no_web:
                parser.error("Cannot use --no-web without a prompt or --resume.")
            from harness.web import start_web_server
            start_web_server(port=args.port, block=True)
        elif args.no_web:
            # Prompt + no web — console only
            from harness.orchestrator import run_project
            run_project(args.prompt, workspace, web=False)
        else:
            # Prompt + web — both
            from harness.orchestrator import run_project
            run_project(args.prompt, workspace, web=True, port=args.port)
    except KeyboardInterrupt:
        print("\n\n[Harness] Interrupted. Progress has been saved — use --resume to continue.")
        sys.exit(1)


if __name__ == "__main__":
    main()
