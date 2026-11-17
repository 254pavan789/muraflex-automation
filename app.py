#!/usr/bin/env python3
"""MURAFLEX AUTOMATION - launcher.

    python app.py                     start the app (opens the browser)
    python app.py --batch FOLDER      convert every FM PDF in FOLDER, one GLASS workbook per PDF
    python app.py --selftest          end-to-end check on generated FM sheets
"""
import sys

from glassx.cli import main

if __name__ == "__main__":
    sys.exit(main())
