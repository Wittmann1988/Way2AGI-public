#!/usr/bin/env python3
"""
Live Persistent Discussion — 4 Way2AGI Agents diskutieren ein TODO.
Zeigt den vollen Dialog in Echtzeit.
"""
import asyncio
import json
import urllib.request
import time
from core.multi_agent_loop import PersistentAgentLoop, AgentConfig, AgentRole


COLORS = {
    "chief": "\033[1;35m",      # Magenta bold
    "reasoner": "\033[1;36m",   # Cyan bold
    "researcher": "\033[1;33m", # Yellow bold
    "archivist": "\033[1;32m",  # Green bold
    "user": "\033[1;37m",       # White bold
    "summary": "\033[1;34m",    # Blue bold
}
RESET = "\033[0m"
DIVIDER = f"\033[90m{'─' * 70}{RESET}"


async def call_model(prompt, model, system=""):
    payload = json.dumps({
        "model": model,
        "prompt": prompt[:800],
        "system": system,
        "stream": False,
        "options": {"num_predict": 200, "repeat_penalty": 1.3},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=180)
    data = json.loads(resp.read())
    return data.get("response", "").strip()


def print_message(msg):
    role = msg["role"]
    rn = msg["round_num"]
    content = msg["content"]
    is_summary = msg.get("is_summary", False)
    is_user = msg.get("is_user", False)

    if is_user:
        color = COLORS["user"]
        label = "USER"
    elif is_summary:
        color = COLORS["summary"]
        label = f"ZUSAMMENFASSUNG R{rn}"
    else:
        color = COLORS.get(role, "")
        label = f"{role.upper()} (Runde {rn})"

    print(DIVIDER)
    print(f"{color}[{label}]{RESET}")
    print(content[:500])
    print()


async def main():
    loop = PersistentAgentLoop(
        call_model_fn=call_model,
        round_pause_s=2.0,
        max_idle_rounds=3,
    )

    # 4 Agents — alle selbst trainiert!
    loop.configure_agents([
        AgentConfig(role=AgentRole.CHIEF, model="way2agi-consciousness-qwen3"),
        AgentConfig(role=AgentRole.REASONER, model="nemotron-3-nano:30b"),
        AgentConfig(role=AgentRole.RESEARCHER, model="huihui_ai/qwen3-abliterated:8b"),
        AgentConfig(role=AgentRole.ARCHIVIST, model="way2agi-memory-qwen3"),
    ])

    # Real-time listener
    loop.add_listener(lambda msg: print_message(msg))

    topic = (
        "TODO T003: Orchestrierung hat ABSOLUTE PRIORITAET. "
        "Wie sollen wir die 4 Compute-Nodes (Inference Node 64GB, Desktop RTX5090, "
        "npu-node NPU, S24 Ultra) am besten orchestrieren? "
        "Welches Modell auf welchem Node? Wie Load-Balancing? "
        "Was ist die optimale Strategie?"
    )

    print(f"\n\033[1;37m{'=' * 70}")
    print(f"  WAY2AGI PERSISTENT MULTI-AGENT DISCUSSION")
    print(f"  Thema: {topic[:80]}...")
    print(f"  Agents: Chief (Consciousness) | Reasoner (Nemotron-30B)")
    print(f"          Researcher (Qwen3-8B) | Archivist (Memory)")
    print(f"{'=' * 70}{RESET}\n")

    await loop.start(topic)

    # 3 Runden laufen lassen
    print("\033[90m>>> Starte 3 Diskussions-Runden...\033[0m\n")
    await asyncio.sleep(90)

    # User-Injection
    print(f"\n\033[1;37m>>> USER INJECTION: Frage wird eingespeist...\033[0m\n")
    await loop.inject_user_message(
        "Soll der Inference Node alleine als Controller reichen oder brauchen wir Redundanz?"
    )
    await asyncio.sleep(50)

    # Stop + Final Summary
    result = await loop.stop()

    print(f"\n\033[1;37m{'=' * 70}")
    print(f"  DISKUSSION BEENDET")
    print(f"  Runden: {result['total_rounds']}")
    print(f"  Nachrichten: {result['total_messages']}")
    print(f"  Dauer: {result['duration_s']}s")
    print(f"{'=' * 70}{RESET}")
    print(f"\n\033[1;34m[FINAL KONSENS]\033[0m")
    print(result.get("consensus", "Kein Konsens")[:600])
    print()


if __name__ == "__main__":
    asyncio.run(main())
