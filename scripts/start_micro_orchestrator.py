#!/usr/bin/env python3
"""Start the Micro-Orchestrator FastAPI service.

Usage:
    python3 scripts/start_micro_orchestrator.py [--device NAME] [--port PORT] [--llama-cpp URL]

Default: device=controller, port=8050
"""
import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.micro_orchestrator import MicroOrchestrator, create_app


def main():
    parser = argparse.ArgumentParser(description="Way2AGI Micro-Orchestrator")
    parser.add_argument("--device", default="controller", help="Device name")
    parser.add_argument("--port", type=int, default=8050, help="Port to listen on")
    parser.add_argument("--ollama", default="http://localhost:11434", help="Ollama URL")
    parser.add_argument("--llama-cpp", default="", help="llama.cpp URL (for SpecDec)")
    args = parser.parse_args()

    orch = MicroOrchestrator(
        device_name=args.device,
        ollama_url=args.ollama,
        llama_cpp_url=args.llama_cpp or None,
        port=args.port,
    )

    app = create_app(orch)

    import uvicorn
    print(f"Starting Micro-Orchestrator '{args.device}' on port {args.port}")
    print(f"Ollama: {args.ollama}")
    if args.llama_cpp:
        print(f"llama.cpp: {args.llama_cpp}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
