#!/usr/bin/env python3
"""
Convenience-Wrapper fuer die Elias Model Build Pipeline.
Eigentliche Logik liegt in training/src/.

Usage:
  python scripts/build_elias_model.py --all
  python scripts/build_elias_model.py --phase 2
"""
import sys
import os

# Projekt-Root zum Path hinzufuegen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training.src.pipeline import main

if __name__ == "__main__":
    main()
