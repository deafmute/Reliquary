#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reliquary.application import ReliquaryApp


def main():
    app = ReliquaryApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
