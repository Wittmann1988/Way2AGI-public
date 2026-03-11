#!/usr/bin/env python3
"""
Jetson-Only Discussion v2: Memory-System Bewertung
Verbesserte System-Prompts + schnellere Modelle
"""
import asyncio
import json
import urllib.request
from core.multi_agent_loop import PersistentAgentLoop, AgentConfig, AgentRole

RESET = "\033[0m"
COLORS = {
    "chief": "\033[1;35m",
    "reasoner": "\033[1;36m",
    "researcher": "\033[1;33m",
    "archivist": "\033[1;32m",
}
DIV = f"\033[90m{'─' * 70}{RESET}"


async def call_model(prompt, model, system=""):
    actual_prompt = prompt[:600]
    # Qwen3/abliterated: force no_think for clean output
    if "qwen3" in model.lower() or "abliterated" in model.lower():
        actual_prompt = "/no_think\n" + actual_prompt

    payload = json.dumps({
        "model": model,
        "prompt": actual_prompt,
        "system": system[:400] if system else "",
        "stream": False,
        "options": {"num_predict": 150, "repeat_penalty": 1.3, "temperature": 0.7},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    text = data.get("response", "").strip()
    # Clean thinking artifacts
    for tag in ["<think>", "</think>", "<output>", "</output>"]:
        text = text.replace(tag, "")
    return text.strip()


def show(msg):
    role = msg["role"]
    rn = msg["round_num"]
    content = msg["content"]
    is_sum = msg.get("is_summary", False)
    is_user = msg.get("is_user", False)

    if is_user:
        c = "\033[1;37m"
        label = "USER"
    elif is_sum:
        c = "\033[1;34m"
        label = f"ZUSAMMENFASSUNG R{rn}"
    else:
        c = COLORS.get(role, "")
        label = f"{role.upper()} R{rn}"

    print(DIV)
    print(f"{c}[{label}]{RESET}")
    for tag in ["<think>", "</think>", "<output>", "</output>"]:
        content = content.replace(tag, "")
    print(content.strip()[:400])
    print()


async def main():
    loop = PersistentAgentLoop(
        call_model_fn=call_model,
        round_pause_s=2.0,
        max_idle_rounds=2,
    )

    # Alle 4 = selbst trainierte Way2AGI Agents!
    loop.configure_agents([
        AgentConfig(role=AgentRole.CHIEF, model="way2agi-consciousness-qwen3"),
        AgentConfig(role=AgentRole.REASONER, model="nemotron-4b-way2agi-v2"),
        AgentConfig(role=AgentRole.RESEARCHER, model="way2agi-orchestrator-qwen3"),
        AgentConfig(role=AgentRole.ARCHIVIST, model="way2agi-memory-qwen3"),
    ])

    loop.add_listener(lambda msg: show(msg))

    topic = (
        "Bewerte unser Six-Layer Memory System kritisch: "
        "1) Episodic Engine (SQLite), 2) Hybrid Store (ChromaDB+Graph), "
        "3) Knowledge Graph, 4) Symbolic Rules, "
        "5) Reflection Agent, 6) Identity Core. "
        "Note 1-10 und Verbesserungsvorschlaege."
    )

    print(f"\n\033[1;37m{'=' * 70}")
    print("  WAY2AGI PERSISTENT DISCUSSION v2")
    print("  Thema: Memory-System Review")
    print("  Alle 4 Agents sind selbst trainierte Way2AGI Modelle!")
    print(f"  Chief: consciousness-qwen3 | Reasoner: nemotron-4b-v2")
    print(f"  Researcher: orchestrator-qwen3 | Archivist: memory-qwen3")
    print(f"{'=' * 70}{RESET}\n")

    await loop.start(topic)

    # 3 Runden
    await asyncio.sleep(100)

    result = await loop.stop()

    print(f"\n\033[1;37m{'=' * 70}")
    print(f"  REVIEW ABGESCHLOSSEN")
    tr = result['total_rounds']
    tm = result['total_messages']
    dur = result['duration_s']
    print(f"  Runden: {tr} | Messages: {tm} | Dauer: {dur}s")
    print(f"{'=' * 70}{RESET}")
    cons = result.get("consensus", "")
    for tag in ["<think>", "</think>"]:
        cons = cons.replace(tag, "")
    print(f"\n\033[1;34m[FINAL KONSENS]{RESET}")
    print(cons.strip()[:600])
    print()


if __name__ == "__main__":
    asyncio.run(main())
