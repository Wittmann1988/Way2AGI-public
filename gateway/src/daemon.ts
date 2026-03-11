#!/usr/bin/env node
/**
 * Way2AGI Gateway Daemon.
 *
 * Central process that runs the cognitive core and exposes:
 * - WebSocket API (port 18789) for clients/channels/devices
 * - HTTP health endpoint
 * - Manages lifecycle of all cognitive modules
 */

import { WebSocketServer, WebSocket } from 'ws';
import { createServer } from 'http';
import {
  createCognitiveCore,
  ReflectionEngine,
  type LLMClient,
  type Layer2Result,
  type Layer3Result,
  type RulePatch,
} from '@way2agi/cognition';

const PORT = parseInt(process.env.WAY2AGI_PORT ?? '18789', 10);
const MEMORY_URL = process.env.WAY2AGI_MEMORY_URL ?? 'http://localhost:8001';
const VERSION = '0.1.0';

// ── Memory Server helpers ───────────────────────────────────────────

async function storeToMemory(
  content: string,
  memoryType: string,
  metadata: Record<string, unknown> = {},
  importance = 0.5,
): Promise<boolean> {
  try {
    const res = await fetch(`${MEMORY_URL}/memory/store`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content,
        memory_type: memoryType,
        metadata,
        importance,
      }),
    });
    if (!res.ok) {
      console.warn(`[Reflection] Memory store returned ${res.status}: ${await res.text()}`);
      return false;
    }
    return true;
  } catch (err) {
    console.warn(`[Reflection] Memory server unreachable (${MEMORY_URL}): ${err}`);
    return false;
  }
}

// ── Stub LLM client (uses orchestrator when available) ──────────────

function createLLMClient(): LLMClient {
  const ORCHESTRATOR_URL = process.env.WAY2AGI_ORCHESTRATOR_URL ?? 'http://localhost:8002';
  return {
    async complete({ model, system, prompt, maxTokens }) {
      try {
        const res = await fetch(`${ORCHESTRATOR_URL}/v1/completions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model, system, prompt, max_tokens: maxTokens }),
        });
        if (!res.ok) throw new Error(`Orchestrator returned ${res.status}`);
        const data = (await res.json()) as { text?: string; completion?: string };
        return data.text ?? data.completion ?? '';
      } catch (err) {
        console.warn(`[Reflection] LLM call failed: ${err}`);
        return JSON.stringify({
          analysis: 'LLM unavailable — returning empty reflection.',
          recommendations: [],
          rulePatches: [],
          strategyInsights: [],
          confidence: 0,
        });
      }
    },
  };
}

interface ClientConnection {
  ws: WebSocket;
  id: string;
  role: 'client' | 'channel' | 'device';
  name: string;
  connectedAt: number;
}

async function main() {
  console.log(`[Way2AGI] Starting Cognitive Gateway Daemon v${VERSION}`);
  console.log(`[Way2AGI] Port: ${PORT}`);

  // Bootstrap cognitive core
  const { workspace, goals, drives, controller, initiative } = createCognitiveCore();

  const clients = new Map<string, ClientConnection>();

  // HTTP server for health checks
  const httpServer = createServer((req, res) => {
    if (req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        status: 'ok',
        version: VERSION,
        uptime: process.uptime(),
        cognitive: {
          workspaceItems: workspace.size,
          activeGoals: goals.getActive().length,
          totalGoals: goals.totalCount,
          drives: drives.getAllStates().map(d => ({
            type: d.type,
            activation: d.activation.toFixed(2),
          })),
          controllerPhase: controller.getPhase(),
          cycleCount: controller.getState().cycleCount,
        },
        connections: clients.size,
      }));
      return;
    }
    res.writeHead(404);
    res.end();
  });

  // WebSocket server (max 1MB messages to prevent DoS)
  const wss = new WebSocketServer({ server: httpServer, maxPayload: 1024 * 1024 });

  wss.on('connection', (ws, req) => {
    const id = crypto.randomUUID();
    const client: ClientConnection = {
      ws,
      id,
      role: 'client',
      name: 'unknown',
      connectedAt: Date.now(),
    };
    clients.set(id, client);

    console.log(`[Gateway] Client connected: ${id}`);

    ws.on('message', (data) => {
      try {
        const msg = JSON.parse(data.toString());
        handleMessage(client, msg);
      } catch {
        ws.send(JSON.stringify({ error: 'Invalid JSON' }));
      }
    });

    ws.on('close', () => {
      clients.delete(id);
      console.log(`[Gateway] Client disconnected: ${id}`);
    });

    // Send welcome
    ws.send(JSON.stringify({
      type: 'welcome',
      id,
      version: VERSION,
      cognitive: {
        activeGoals: goals.getActive().length,
        drives: drives.getAllStates().map(d => d.type),
      },
    }));
  });

  function handleMessage(client: ClientConnection, msg: Record<string, unknown>) {
    const type = msg.type as string;

    switch (type) {
      case 'identify': {
        const allowedRoles: ClientConnection['role'][] = ['client', 'channel', 'device'];
        const requestedRole = msg.role as string;
        client.role = allowedRoles.includes(requestedRole as any) ? requestedRole as ClientConnection['role'] : 'client';
        // Sanitize name: alphanumeric, dash, underscore only (max 32 chars)
        const rawName = (msg.name as string) ?? 'unknown';
        client.name = rawName.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 32) || 'unknown';
        break;
      }

      case 'perception':
        // External input enters the workspace
        workspace.post({
          type: 'perception',
          priority: (msg.priority as number) ?? 5,
          payload: msg.payload,
          sourceModule: `channel:${client.name}`,
          ttl: 30_000,
        });
        break;

      case 'goal:create':
        goals.create({
          type: (msg.goalType as any) ?? 'task',
          description: (msg.description as string) ?? '',
          priority: (msg.priority as number) ?? 5,
          source: 'user',
          context: (msg.context as Record<string, unknown>) ?? {},
        });
        break;

      case 'status':
        client.ws.send(JSON.stringify({
          type: 'status',
          cognitive: controller.getState(),
          goals: goals.getTopPriority(10),
          drives: drives.getAllStates(),
        }));
        break;
    }
  }

  // Broadcast workspace events to all connected clients
  workspace.observe().subscribe(event => {
    const msg = JSON.stringify({ type: 'cognitive:event', event });
    for (const client of clients.values()) {
      if (client.ws.readyState === WebSocket.OPEN) {
        try {
          client.ws.send(msg);
        } catch {
          // Client may have disconnected between readyState check and send
        }
      }
    }
  });

  // Set up Layer 2/3 reflection handler — full Think→Act→Reflect→Learn loop
  const llmClient = createLLMClient();
  const reflectionEngine = new ReflectionEngine(workspace, goals, llmClient);

  controller.onReflection(async (req) => {
    console.log(`[Reflection] Layer ${req.layer} triggered: ${req.trigger} (urgency: ${req.urgency})`);

    // 1. Run reflection via ReflectionEngine (calls LLM, applies recommendations/patches)
    let result: Layer2Result | Layer3Result;
    try {
      result = await reflectionEngine.reflect(req);
    } catch (err) {
      console.error(`[Reflection] Engine error:`, err);
      // Graceful degradation: post raw request so the cycle doesn't break
      workspace.post({
        type: 'reflection',
        priority: req.urgency,
        payload: { error: String(err), request: req },
        sourceModule: `reflection:layer${req.layer}`,
        ttl: 60_000,
      });
      return;
    }

    console.log(`[Reflection] Layer ${req.layer} completed in ${result.durationMs}ms (confidence: ${result.confidence})`);

    // 2. Store action results as episodic memory
    const memoryStored = await storeToMemory(
      `[Layer ${req.layer} Reflection] Trigger: ${req.trigger}. ${result.analysis}`,
      'episodic',
      {
        source: 'reflection-engine',
        layer: req.layer,
        trigger: req.trigger,
        confidence: result.confidence,
        durationMs: result.durationMs,
        urgency: req.urgency,
      },
      Math.min(1.0, 0.3 + result.confidence * 0.5),
    );

    if (!memoryStored) {
      console.warn('[Reflection] Could not persist reflection to memory — continuing anyway');
    }

    // 3. Extract and store lessons
    if ('recommendations' in result && result.recommendations.length > 0) {
      // Layer 2: store each non-trivial recommendation as a lesson
      const actionableRecs = result.recommendations.filter(r => r.action !== 'ignore');
      if (actionableRecs.length > 0) {
        const lessonContent = actionableRecs
          .map(r => `[${r.action}] ${r.description}${r.goalId ? ` (goal: ${r.goalId})` : ''}`)
          .join('\n');

        await storeToMemory(
          `[Lesson L2] ${req.trigger}: ${lessonContent}`,
          'semantic',
          {
            source: 'reflection-lesson',
            layer: 2,
            trigger: req.trigger,
            recommendation_count: actionableRecs.length,
          },
          0.6 + result.confidence * 0.3,
        );
      }
    }

    if ('strategyInsights' in result && result.strategyInsights.length > 0) {
      // Layer 3: store strategy insights as semantic lessons
      await storeToMemory(
        `[Lesson L3] Strategy insights from ${req.trigger}:\n${result.strategyInsights.join('\n')}`,
        'semantic',
        {
          source: 'reflection-lesson',
          layer: 3,
          trigger: req.trigger,
          insight_count: result.strategyInsights.length,
        },
        0.7 + result.confidence * 0.2,
      );
    }

    // 4. Forward RulePatches to MetaController via workspace
    if ('rulePatches' in result && result.rulePatches.length > 0) {
      console.log(`[Reflection] Applying ${result.rulePatches.length} rule patches`);
      // The ReflectionEngine already posts patches to workspace (see reflection.ts L354-367)
      // Additionally store them as procedural memory for long-term retention
      await storeToMemory(
        `[RulePatches] ${result.rulePatches.map((p: RulePatch) => `${p.id}: ${p.description}`).join('; ')}`,
        'procedural',
        {
          source: 'reflection-rules',
          layer: 3,
          patches: result.rulePatches,
          confidence: result.confidence,
        },
        0.8,
      );
    }

    // 5. Broadcast reflection result to connected clients
    const broadcastMsg = JSON.stringify({
      type: 'reflection:complete',
      layer: req.layer,
      trigger: req.trigger,
      confidence: result.confidence,
      durationMs: result.durationMs,
      analysis: result.analysis,
    });

    for (const client of clients.values()) {
      if (client.ws.readyState === WebSocket.OPEN) {
        try {
          client.ws.send(broadcastMsg);
        } catch {
          // Client may have disconnected
        }
      }
    }
  });

  // Start cognitive systems
  controller.start();
  initiative.start();

  httpServer.listen(PORT, () => {
    console.log(`[Way2AGI] Gateway running on port ${PORT}`);
    console.log(`[Way2AGI] Health: http://localhost:${PORT}/health`);
    console.log(`[Way2AGI] WebSocket: ws://localhost:${PORT}`);
    console.log(`[Way2AGI] Cognitive core active — MetaController + Initiative Engine running`);
  });

  // Graceful shutdown
  const shutdown = () => {
    console.log('\n[Way2AGI] Shutting down...');
    controller.stop();
    initiative.stop();
    wss.close();
    httpServer.close();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

main().catch(err => {
  console.error('[Way2AGI] Fatal error:', err);
  process.exit(1);
});
