import sys

from .app import StickyApp


def main():
    return StickyApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
