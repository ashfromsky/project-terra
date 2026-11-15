"""CLI entrypoint for running the PROJECT TERRA Scientific Assessment worker."""

import argparse
import asyncio
import logging
import signal

from terra.config import get_settings

from terra_worker.runner import AssessmentWorkerRunner


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PROJECT TERRA Scientific Assessment worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim and process at most one queued assessment, then exit.",
    )
    parser.add_argument(
        "--drain",
        action="store_true",
        help="Drain all currently queued assessments, then exit.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Idle polling interval in seconds (default: 2.0).",
    )
    return parser.parse_args()


async def _run_async(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    runner = AssessmentWorkerRunner(
        settings=get_settings(),
        poll_interval_seconds=args.poll_interval,
    )
    if args.once:
        await runner.initialize()
        try:
            await runner.run_once()
        finally:
            await runner.dispose()
        return

    if args.drain:
        await runner.initialize()
        try:
            await runner.drain_queue()
        finally:
            await runner.dispose()
        return

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await runner.run_forever(stop_event=stop_event)


def main() -> None:
    """Execute the worker CLI."""
    args = _parse_args()
    asyncio.run(_run_async(args))


if __name__ == "__main__":
    main()
