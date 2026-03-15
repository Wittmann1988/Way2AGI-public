#!/usr/bin/env python3
"""Quick test: 2-agent persistent discussion on Inference Node."""
import asyncio
import json
import urllib.request
from core.multi_agent_loop import PersistentAgentLoop, AgentConfig, AgentRole


async def call_model(prompt, model, system=""):
    payload = json.dumps({
        "model": model,
        "prompt": prompt[:500],
        "system": system,
        "stream": False,
        "options": {"num_predict": 150},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    return data.get("response", "")


async def main():
    loop = PersistentAgentLoop(
        call_model_fn=call_model,
        round_pause_s=1.0,
        max_idle_rounds=2,
    )
    loop.configure_agents([
        AgentConfig(role=AgentRole.CHIEF, model="way2agi-consciousness-qwen3"),
        AgentConfig(role=AgentRole.REASONER, model="nemotron-4b-way2agi-v2"),
    ])

    await loop.start("Wie kann das Memory-System verbessert werden?")

    # Wait for 2 rounds
    print("Warte auf 2 Runden...")
    await asyncio.sleep(40)

    # Inject user message
    print("Injecting user message...")
    await loop.inject_user_message("Was ist mit ChromaDB als Vector Store?")
    await asyncio.sleep(25)

    result = await loop.stop()
    print("=== RESULT ===")
    tr = result["total_rounds"]
    tm = result["total_messages"]
    dur = result["duration_s"]
    cons = result["consensus"][:400]
    print(f"Runden: {tr}")
    print(f"Messages: {tm}")
    print(f"Duration: {dur}s")
    print(f"Konsens: {cons}")

    # Show messages
    for msg in loop.get_full_log():
        role = msg["role"]
        rn = msg["round_num"]
        content = msg["content"][:200]
        print(f"\n[{role}] R{rn}: {content}")


if __name__ == "__main__":
    asyncio.run(main())
