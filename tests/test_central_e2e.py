#!/usr/bin/env python3
"""End-to-End Test: CentralOrchestrator
Testet: Health check, Bid collection, Execute across devices
Voraussetzung: MicroOrchestrator laeuft auf controller:8051
"""
import asyncio
import sys
sys.path.insert(0, "/home/YOUR_USER/repos/Way2AGI-public")

from core.central_orchestrator import CentralOrchestrator

async def main():
    print("=" * 60)
    print("CentralOrchestrator E2E Test")
    print("=" * 60)

    co = CentralOrchestrator()
    # Register devices — controller has MicroOrchestrator on 8051
    co.register_device("controller", "127.0.0.1", 8051)
    # Desktop doesn't have MicroOrchestrator yet, skip for now

    # 1. Health check
    print("\n--- 1. Health Check ---")
    health = await co.check_all_devices()
    for name, status in health.items():
        print(f"  {name}: {status}")

    # 2. Discover capabilities
    print("\n--- 2. Capabilities ---")
    caps = await co.discover_all_capabilities()
    for name, cap in caps.items():
        print(f"  {name}: {cap.get('model_count')} Modelle, uptime={cap.get('uptime_s')}s")

    # 3. Orchestrate a simple task
    print("\n--- 3. Orchestrate: Einfache Aufgabe ---")
    task1 = "Was ist der aktuelle Status des Systems?"
    result1 = await co.orchestrate(task1)
    print(f"  Device: {result1['routing'].get('device')}")
    print(f"  Model: {result1['routing'].get('model')}")
    print(f"  Response: {result1['result'][:300]}")
    print(f"  Duration: {result1['duration_s']}s")

    # 4. Orchestrate a reasoning task
    print("\n--- 4. Orchestrate: Reasoning ---")
    task2 = "Warum ist Speculative Decoding schneller als normales Autoregressive Decoding?"
    result2 = await co.orchestrate(task2, strategy="best")
    print(f"  Device: {result2['routing'].get('device')}")
    print(f"  Model: {result2['routing'].get('model')}")
    print(f"  Confidence: {result2['routing'].get('confidence')}")
    print(f"  Response: {result2['result'][:400]}")
    print(f"  Duration: {result2['duration_s']}s")

    # 5. Status
    print("\n--- 5. Status ---")
    status = co.get_status()
    print(f"  Active: {status['active']}/{status['total']}")
    print(f"  Uptime: {status['uptime_s']}s")

    print("\n" + "=" * 60)
    print("CENTRAL ORCHESTRATOR TEST ABGESCHLOSSEN")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
