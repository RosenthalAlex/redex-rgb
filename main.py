#!/usr/bin/env python3
"""redex - RGB control for the Trust GXT 926 Redex II mouse.

  redex                 open the window
  redex --background    keep the LEDs in the GNOME accent color (used by redex-accent.service)
  redex <command> ...   command line: status, top, bottom, effect, effects, restore (see redex --help)
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))


def main():
    args = sys.argv[1:]
    if not args:
        import redex_gui
        return redex_gui.main([sys.argv[0]])
    if args[0] == "--background":
        import redex_accent
        return redex_accent.main()
    import redex
    return redex.main()


if __name__ == "__main__":
    sys.exit(main())
