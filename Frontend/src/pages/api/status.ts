import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';

export const prerender = false;

export const GET: APIRoute = async () => {
  const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
  let state = { status: 'IDLE', startedAt: 0 };

  try {
    const data = await fs.readFile(statePath, 'utf-8');
    state = JSON.parse(data);
  } catch (err) {
    // If state file doesn't exist, we treat as IDLE
    try {
      await fs.writeFile(statePath, JSON.stringify(state, null, 2));
    } catch (writeErr) {
      console.error('Failed to create state file:', writeErr);
    }
  }

  // Check for 9 seconds processing duration and transition to READY
  if (state.status === 'PROCESSING') {
    const elapsed = Date.now() - state.startedAt;
    if (elapsed >= 9000) {
      state.status = 'READY';
      try {
        await fs.writeFile(statePath, JSON.stringify(state, null, 2));
      } catch (writeErr) {
        console.error('Failed to update state file to READY:', writeErr);
      }
    }
  }

  return new Response(JSON.stringify({ status: state.status }), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    },
  });
};
