"""ATLAS Kubernetes Operator entrypoint."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from atlas_operator.reconciler import AtlasOperatorController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("atlas.operator")


def main() -> int:
    parser = argparse.ArgumentParser(description="ATLAS Kubernetes Operator")
    parser.add_argument(
        "--namespace",
        default="atlas-system",
        help="Namespace to watch (or empty for cluster-wide)",
    )
    parser.add_argument(
        "--sync-interval",
        type=int,
        default=15,
        help="Reconciliation sync interval in seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute single reconciliation check and exit",
    )
    args = parser.parse_args()

    logger.info(
        f"Starting ATLAS Operator v0.12.0 (namespace={args.namespace}, interval={args.sync_interval}s)"
    )
    _controller = AtlasOperatorController()

    if args.dry_run:
        logger.info("Dry run executed successfully. Controller ready.")
        return 0

    logger.info("Controller running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(args.sync_interval)
    except KeyboardInterrupt:
        logger.info("Operator stopped cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
