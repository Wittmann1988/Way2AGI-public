"""
Way2AGI — Elias Model Build Pipeline Orchestrator.
===================================================
Steuert alle 5 Phasen der Model-Erstellung.

Usage:
  python -m training.src.pipeline --all
  python -m training.src.pipeline --phase 2
  python -m training.src.pipeline --phase 1 --phase 2  # Mehrere Phasen
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from . import abliterate, distill, train_sft, publish, convert_gguf
from .config import ARTIFACTS_DIR, LOG_FILE

PHASES = {
    1: ("PRISM Abliteration", abliterate.run),
    2: ("Knowledge Distillation", distill.run),
    3: ("SFT Training", train_sft.run),
    4: ("Publish HuggingFace", publish.run),
    5: ("GGUF Konvertierung", convert_gguf.run),
}


def setup_logging():
    """Konfiguriert Logging in Datei + stdout."""
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_pipeline(phases):
    """Fuehrt die angegebenen Phasen aus."""
    log = logging.getLogger("elias-build")

    log.info("=" * 60)
    log.info("WAY2AGI — ELIAS MODEL BUILD PIPELINE")
    log.info("Gestartet: %s", datetime.now().isoformat())
    log.info("Phasen: %s", [PHASES[p][0] for p in phases])
    log.info("Artifacts: %s", ARTIFACTS_DIR)
    log.info("=" * 60)

    t0 = time.time()

    for phase_num in phases:
        name, func = PHASES[phase_num]
        log.info(">>> Starte Phase %d: %s", phase_num, name)
        phase_start = time.time()
        func()
        log.info("<<< Phase %d fertig in %.0fs", phase_num, time.time() - phase_start)

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("PIPELINE FERTIG. Gesamtdauer: %.0f Minuten", elapsed / 60)
    log.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Way2AGI Elias Model Build Pipeline")
    parser.add_argument("--all", action="store_true", help="Alle 5 Phasen ausfuehren")
    parser.add_argument("--phase", type=int, action="append", choices=[1, 2, 3, 4, 5],
                        help="Phase(n) ausfuehren (wiederholbar)")
    args = parser.parse_args()

    setup_logging()

    if args.all:
        run_pipeline([1, 2, 3, 4, 5])
    elif args.phase:
        run_pipeline(sorted(set(args.phase)))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
