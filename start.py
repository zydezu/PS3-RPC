#!/usr/bin/env python3
import sys


def main():
    if getattr(sys, "frozen", False):
        from ps3rpc.__main__ import main as run

        run()
    else:
        from ps3rpc.__main__ import main as run

        run()


if __name__ == "__main__":
    main()
