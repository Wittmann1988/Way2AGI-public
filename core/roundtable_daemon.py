#!/usr/bin/env python3
"""Persistent Roundtable Daemon — runs multi-agent discussion in a loop."""
import asyncio
import logging
import sys
import os
import time

sys.path.insert(0, "/opt/way2agi/Way2AGI")

from core.multi_agent_loop import PersistentAgentLoop, AgentConfig, AgentRole

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("roundtable-daemon")

# primary-node agents — use local Ollama models
def get_primary_node_agents():
    return [
        AgentConfig(
            role=AgentRole.CHIEF,
            model="olmo-3:7b-think",
            node="primary-node",
        ),
        AgentConfig(
            role=AgentRole.REASONER,
            model="lfm2:24b",
            node="primary-node",
        ),
        AgentConfig(
            role=AgentRole.RESEARCHER,
            model="qwen3.5:0.8b",
            node="primary-node",
        ),
        AgentConfig(
            role=AgentRole.ARCHIVIST,
            model="qwen3.5:0.8b",
            node="primary-node",
        ),
    ]

import aiohttp

OLLAMA_URL = "http://localhost:11434"

async def call_ollama(prompt: str, model: str, system: str = "") -> str:
    """Direct Ollama API call for roundtable."""
    payload = {
        "model": model,
        "messages": [],
        "stream": False,
        "options": {"num_predict": 512},
    }
    if system:
        payload["messages"].append({"role": "system", "content": system})
    payload["messages"].append({"role": "user", "content": prompt})
    
    # Disable thinking for qwen3 models
    if "qwen3" in model.lower():
        payload["options"]["think"] = False
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            data = await resp.json()
            return data.get("message", {}).get("content", "")

TOPICS = [
    "Wie koennen wir die Way2AGI Architektur verbessern? Fokus: Memory-System, Orchestrierung, Self-Improvement.",
    "Welche Tasks sind offen und wie priorisieren wir sie? Analyse der aktuellen TODOs.",
    "Self-Reflection: Was laeuft gut, was laeuft schlecht im aktuellen System?",
]

async def run_forever():
    log.info("Persistent Roundtable Daemon gestartet")
    topic_idx = 0
    
    while True:
        topic = TOPICS[topic_idx % len(TOPICS)]
        log.info("Starte Discussion: %s", topic[:80])
        
        try:
            loop = PersistentAgentLoop(call_model_fn=call_ollama, round_pause_s=10.0, max_idle_rounds=5)
            loop.configure_agents(get_primary_node_agents())
            await loop.start(topic)
            
            # Wait for the discussion task to complete
            if loop._task:
                await loop._task
            
            log.info("Discussion abgeschlossen: %d Nachrichten, %d Runden",
                      len(loop.state.messages), loop.state.total_rounds)
            
            # Save to memory if possible
            try:
                await loop.save_to_memory()
                log.info("Ergebnis in Memory gespeichert")
            except Exception as e:
                log.warning("Memory-Save fehlgeschlagen: %s", e)
                
        except Exception as e:
            log.error("Discussion Fehler: %s", e, exc_info=True)
        
        topic_idx += 1
        # Wait 30 minutes between discussions
        log.info("Naechste Discussion in 30 Minuten...")
        await asyncio.sleep(1800)

if __name__ == "__main__":
    asyncio.run(run_forever())
