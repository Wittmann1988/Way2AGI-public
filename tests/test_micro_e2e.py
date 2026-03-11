#!/usr/bin/env python3
"""End-to-End Test: MicroOrchestrator auf Jetson
Testet: bid + execute mit qwen3.5:0.8b
"""
import asyncio
import sys
sys.path.insert(0, "/home/jetson/repos/Way2AGI-public")

from core.micro_orchestrator import MicroOrchestrator

async def main():
    print("=" * 60)
    print("MicroOrchestrator E2E Test auf Jetson")
    print("=" * 60)

    orch = MicroOrchestrator(
        device_name="controller",
        ollama_url="http://localhost:11434",
    )

    # 1. Discover models
    print("\n--- 1. Model Discovery ---")
    models = await orch.discover_models()
    print(f"Gefunden: {len(models)} Modelle")
    for name, m in sorted(models.items(), key=lambda x: x[1].size_gb):
        print(f"  {name}: {m.size_gb:.1f}GB, backend={m.backend}")

    # 2. Simple system task → should pick smallest model
    print("\n--- 2. Bid: Einfache System-Aufgabe ---")
    task1 = "Liste alle verfuegbaren Modelle auf diesem Geraet"
    bid1 = orch.bid_on_task(task1)
    print(f"Task: {task1}")
    print(f"Bid: model={bid1.model}, confidence={bid1.confidence}, reason={bid1.reason}")

    # 3. Execute the simple task
    print("\n--- 3. Execute: Einfache Aufgabe ---")
    result1 = await orch.execute_task(task1)
    print(f"Model used: {result1.get('model')}")
    print(f"Response: {result1.get('response', '')[:300]}")
    print(f"Duration: {result1.get('duration_s')}s")

    # 4. Reasoning task → should pick larger model
    print("\n--- 4. Bid: Reasoning-Aufgabe ---")
    task2 = "Erklaere den Unterschied zwischen Transformer und Mamba Architektur"
    bid2 = orch.bid_on_task(task2)
    print(f"Task: {task2}")
    print(f"Bid: model={bid2.model}, confidence={bid2.confidence}")

    # 5. Memory task → should pick memory agent if available
    print("\n--- 5. Bid: Memory-Aufgabe ---")
    task3 = "Erinnere dich an die letzte Session und was wir besprochen haben"
    bid3 = orch.bid_on_task(task3)
    print(f"Task: {task3}")
    print(f"Bid: model={bid3.model}, confidence={bid3.confidence}")

    # 6. Execute reasoning task
    print("\n--- 6. Execute: Reasoning-Aufgabe ---")
    result2 = await orch.execute_task(task2)
    print(f"Model used: {result2.get('model')}")
    print(f"Response: {result2.get('response', '')[:400]}")
    print(f"Duration: {result2.get('duration_s')}s")

    print("\n" + "=" * 60)
    print("TEST ABGESCHLOSSEN")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
