#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backward-compatible wrapper for the Hendrik tip bot."""

import os
import sys

sys.path.append(os.path.dirname(__file__))
from tipp_bot import main

if __name__ == "__main__":
    sys.exit(main(["--profile", "hendrik"] + sys.argv[1:]))
