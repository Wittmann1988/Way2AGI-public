# core/watchdog.py — Universal watchdog for any Way2AGI node
import asyncio
import logging
import time
from typing import Dict, List

try:
    from core.config import config
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.config import config

log = logging.getLogger("way2agi-watchdog")


class NodeWatchdog:
    """Monitors all registered nodes and restarts services if needed."""

    def __init__(self):
        self.node_status: Dict[str, dict] = {}
        self.check_interval = 60  # seconds

    async def check_node(self, name: str, ip: str, port: int) -> dict:
        import aiohttp
        url = f"http://{ip}:{port}/health"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"name": name, "status": "up", "data": data}
        except Exception as e:
            return {"name": name, "status": "down", "error": str(e)}
        return {"name": name, "status": "down", "error": "unknown"}

    async def check_all_nodes(self) -> List[dict]:
        nodes_to_check = []
        if config.CONTROLLER_IP:
            nodes_to_check.append(("controller", config.CONTROLLER_IP, 8050))
        if config.DESKTOP_IP:
            nodes_to_check.append(("desktop", config.DESKTOP_IP, 8100))
        if config.LAPTOP_IP:
            nodes_to_check.append(("laptop", config.LAPTOP_IP, 8150))
        if config.MOBILE_IP:
            nodes_to_check.append(("mobile", config.MOBILE_IP, 8200))

        tasks = [self.check_node(n, ip, p) for n, ip, p in nodes_to_check]
        results = await asyncio.gather(*tasks)

        for r in results:
            self.node_status[r["name"]] = r
            if r["status"] == "down":
                log.warning(f"Node {r['name']} is DOWN: {r.get('error')}")
            else:
                log.info(f"Node {r['name']} is UP")

        return results

    async def run(self):
        log.info("Watchdog started")
        while True:
            await self.check_all_nodes()
            await asyncio.sleep(self.check_interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    watchdog = NodeWatchdog()
    asyncio.run(watchdog.run())
