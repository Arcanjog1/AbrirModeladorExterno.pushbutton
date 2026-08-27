# -*- coding: utf-8 -*-
"""Roda a suite de testes do Script.py fora do Revit. Ver test_script.py."""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_script  # noqa: E402


def main():
    failures = []
    for func in test_script.CASES:
        try:
            func()
            print("  ok   {}".format(func.__name__))
        except Exception:
            failures.append((func.__name__, traceback.format_exc()))
            print("  FALHA {}".format(func.__name__))
    print("")
    print("{} teste(s), {} falha(s)".format(len(test_script.CASES), len(failures)))
    for name, tb in failures:
        print("")
        print("=== {} ===".format(name))
        print(tb)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
