#!/usr/bin/env python3
"""Open the RK3588 training station camera and preview harness detections."""

import sys

from safety_harness import main as run_detection


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    return run_detection(['--show', *argv])


if __name__ == '__main__':
    sys.exit(main())
