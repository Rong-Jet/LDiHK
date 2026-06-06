import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';

export const prerender = false;

// Handle OPTIONS preflight requests for CORS compatibility
export const OPTIONS: APIRoute = async () => {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
    },
  });
};

export const POST: APIRoute = async ({ request }) => {
  try {
    const authHeader = request.headers.get('Authorization') || '';
    if (!authHeader.startsWith('Bearer ')) {
      return new Response(JSON.stringify({ error: 'missing_authorization' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    const ldihkId = authHeader.replace('Bearer ', '').trim();
    if (!ldihkId) {
      return new Response(JSON.stringify({ error: 'invalid_authorization' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    const body = await request.json();
    const { dataset, metrics = [], dimensions = [], filters = {} } = body;
    
    // Check if the dataset is ready in mock database
    const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
    let state: any = { datasets: {} };
    try {
      const stateContent = await fs.readFile(statePath, 'utf-8');
      state = JSON.parse(stateContent);
    } catch (err) {
      // Fallback
    }

    const isYoutubeReady = state.datasets?.youtube?.status === 'READY';
    
    if (!dataset) {
      return new Response(JSON.stringify({ error: 'invalid_dataset' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    if (dataset !== 'youtube_usage') {
      return new Response(JSON.stringify({ error: 'invalid_dataset' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    if (metrics.length === 0) {
      return new Response(JSON.stringify({ error: 'invalid_metrics' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    if (!isYoutubeReady) {
      return new Response(
        JSON.stringify({
          schema_version: 'youtube_usage.structured_query.v1',
          dataset,
          ldihk_id: ldihkId,
          query: body,
          rows: [],
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        }
      );
    }

    // Parse filters
    const startDateStr = filters.start_date || '2026-05-08';
    const endDateStr = filters.end_date || '2026-06-06';
    
    const start = new Date(startDateStr);
    const end = new Date(endDateStr);

    const [y1, m1, d1] = startDateStr.split('-').map(Number);
    const [y2, m2, d2] = endDateStr.split('-').map(Number);
    const startUTC = Date.UTC(y1, m1 - 1, d1);
    const endUTC = Date.UTC(y2, m2 - 1, d2);
    const diffMs = endUTC - startUTC;
    const dayCount = Math.max(1, Math.round(diffMs / (1000 * 3600 * 24)) + 1);

    // 1. Grouping by both Date and Hour (for heatmap)
    if (dimensions.includes('date') && dimensions.includes('hour')) {
      const rows = [];
      const current = new Date(start);

      while (current <= end) {
        const dateString = current.toISOString().split('T')[0];
        
        for (let hour = 0; hour < 24; hour++) {
          let weight = 1;
          if (hour >= 1 && hour <= 5) weight = 0.1;
          else if (hour >= 8 && hour <= 11) weight = 1.2;
          else if (hour >= 12 && hour <= 17) weight = 1.5;
          else if (hour >= 18 && hour <= 22) weight = 2.8;
          else weight = 1.4;

          const baseSecs = 1200; // YouTube watch seconds base
          const pseudoRand = Math.sin(hour + current.getTime() + 5) * 0.2 + 1;
          
          const watchSeconds = Math.max(0, Math.round(baseSecs * weight * pseudoRand));
          const eventCount = Math.max(0, Math.round(watchSeconds / 300));

          rows.push({
            date: dateString,
            hour,
            event_count: eventCount,
            estimated_watch_seconds: watchSeconds,
          });
        }
        current.setDate(current.getDate() + 1);
      }

      return new Response(
        JSON.stringify({
          schema_version: 'youtube_usage.structured_query.v1',
          dataset,
          ldihk_id: ldihkId,
          query: body,
          rows,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        }
      );
    }

    // 2. Grouping by Date (for timeline chart)
    if (dimensions.includes('date')) {
      const rows = [];
      const current = new Date(start);
      
      while (current <= end) {
        const dateString = current.toISOString().split('T')[0];
        const dayOfWeek = current.getDay();
        const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
        
        const baseHoursMultiplier = isWeekend ? 1.5 : 1.0;
        const d = current.getDate();
        const trend = 1 + (d / 30) * 0.2; 
        const avgHours = 2.4; // youtube average watch hours

        const pseudoRand = Math.sin(current.getTime() + 12) * 0.25 + 1;
        const watchHours = Math.max(0, avgHours * baseHoursMultiplier * trend * pseudoRand);
        const watchSeconds = Math.round(watchHours * 3600);
        const eventCount = Math.round(watchHours * 10);

        rows.push({
          date: dateString,
          event_count: eventCount,
          estimated_watch_seconds: watchSeconds,
        });

        current.setDate(current.getDate() + 1);
      }

      return new Response(
        JSON.stringify({
          schema_version: 'youtube_usage.structured_query.v1',
          dataset,
          ldihk_id: ldihkId,
          query: body,
          rows,
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        }
      );
    }

    // Default aggregate fallback (single row)
    return new Response(
      JSON.stringify({
        schema_version: 'youtube_usage.structured_query.v1',
        dataset,
        ldihk_id: ldihkId,
        query: body,
        rows: [
          {
            event_count: 500,
            estimated_watch_seconds: 180000,
          }
        ],
      }),
      {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      }
    );
  } catch (err: any) {
    console.error('Query endpoint crash:', err);
    return new Response(JSON.stringify({ error: 'invalid_payload' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
};
