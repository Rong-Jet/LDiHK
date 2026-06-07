import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import { isMockApiMode, shouldAllowImplicitMockApiMode } from '../../lib/env';

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

function getHourlyMockRecord(platform: string, dateStr: string, hour: number) {
  const yearStr = dateStr.substring(0, 4);
  const monthStr = dateStr.substring(5, 7);
  const dayStr = dateStr.substring(8, 10);

  const year = parseInt(yearStr) || 2026;
  const month = parseInt(monthStr) || 6;
  const day = parseInt(dayStr) || 6;

  let platformOffset = 0;
  if (platform === 'instagram') platformOffset = 50;
  else if (platform === 'tiktok') platformOffset = 100;
  else if (platform === 'spotify') platformOffset = 120;
  else if (platform === 'twitter') platformOffset = 150;
  else if (platform === 'linkedin') platformOffset = 200;

  const seed = (year * 367) + (month * 31) + day + hour * 17 + platformOffset;
  const rand = Math.abs(Math.sin(seed + 12.34)) * 0.8 + 0.2;

  const dObj = new Date(year, month - 1, day);
  const dayOfWeek = dObj.getDay();
  const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
  const weekendMult = isWeekend ? 1.45 : 0.95;

  const epochDays = Math.round((dObj.getTime() - new Date('2016-01-01').getTime()) / (1000 * 3600 * 24));
  const seasonalTrend = 1.0 + Math.sin(epochDays / 120) * 0.25;
  const longTermTrend = 1.0 + (epochDays / 3652.5) * 0.35;

  let hourWeight = 1.0;
  let baseSeconds = 850;
  let eventDivisor = 270;

  if (platform === 'youtube') {
    if (hour >= 23 || hour <= 4) {
      hourWeight = isWeekend
        ? (hour === 23 || hour === 0 ? 1.9 : 0.9)
        : (hour === 23 || hour === 0 ? 0.7 : 0.15);
    } else if (hour >= 5 && hour <= 8) {
      hourWeight = 0.1;
    } else if (hour >= 9 && hour <= 12) {
      hourWeight = 0.65;
    } else if (hour >= 13 && hour <= 17) {
      hourWeight = 1.1;
    } else if (hour >= 18 && hour <= 22) {
      hourWeight = 2.4;
    }
    baseSeconds = 850;
    eventDivisor = 270;
  } else if (platform === 'instagram') {
    if (hour >= 23 || hour <= 6) {
      hourWeight = isWeekend ? 0.3 : 0.15;
    } else if (hour >= 7 && hour <= 8) {
      hourWeight = 1.0;
    } else if (hour >= 9 && hour <= 11) {
      hourWeight = 1.2;
    } else if (hour >= 12 && hour <= 14) {
      hourWeight = 1.4;
    } else if (hour >= 15 && hour <= 17) {
      hourWeight = 1.1;
    } else if (hour >= 18 && hour <= 22) {
      hourWeight = 1.6;
    }
    baseSeconds = 420;
    eventDivisor = 45;
  } else if (platform === 'tiktok') {
    if (hour >= 22 || hour <= 2) {
      hourWeight = isWeekend ? 3.5 : 2.5;
    } else if (hour >= 3 && hour <= 6) {
      hourWeight = 0.1;
    } else if (hour >= 7 && hour <= 11) {
      hourWeight = 0.4;
    } else if (hour >= 12 && hour <= 14) {
      hourWeight = 0.8;
    } else if (hour >= 15 && hour <= 17) {
      hourWeight = 0.9;
    } else if (hour >= 18 && hour <= 21) {
      hourWeight = 1.8;
    }
    baseSeconds = 630;
    eventDivisor = 90;
  } else if (platform === 'spotify') {
    if (hour >= 23 || hour <= 5) {
      hourWeight = 0.15;
    } else if (hour >= 9 && hour <= 17) {
      hourWeight = 1.8;
    } else if (hour >= 18 && hour <= 22) {
      hourWeight = 1.2;
    } else {
      hourWeight = 0.7;
    }
    baseSeconds = 540;
    eventDivisor = 180;
  } else {
    if (hour >= 23 || hour <= 5) {
      hourWeight = 0.2;
    } else if (hour >= 9 && hour <= 17) {
      hourWeight = 1.5;
    } else {
      hourWeight = 0.8;
    }
    baseSeconds = 200;
    eventDivisor = 60;
  }

  const watchSeconds = Math.max(0, Math.round(baseSeconds * hourWeight * weekendMult * seasonalTrend * longTermTrend * rand));
  const eventCount = watchSeconds > 0 ? Math.max(1, Math.round(watchSeconds / eventDivisor)) : 0;

  return {
    date: dateStr,
    hour,
    estimated_watch_seconds: watchSeconds,
    event_count: eventCount
  };
}

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

    if (!dataset) {
      return new Response(JSON.stringify({ error: 'invalid_dataset' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    const platform = dataset.replace('_usage', '');
    const allowedPlatforms = ['youtube', 'instagram', 'tiktok', 'spotify', 'twitter', 'linkedin'];
    if (!allowedPlatforms.includes(platform)) {
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

    if (!isMockApiMode && !shouldAllowImplicitMockApiMode) {
      return new Response(JSON.stringify({ error: 'backend_not_configured' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    // Check if the dataset is ready in mock database
    const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
    let state: any = { datasets: {} };
    try {
      const stateContent = await fs.readFile(statePath, 'utf-8');
      state = JSON.parse(stateContent);
    } catch (err) {
      // Fallback
    }

    const isReady = isMockApiMode || state.datasets?.[platform]?.status === 'READY';

    if (!isReady) {
      return new Response(
        JSON.stringify({
          schema_version: `${platform}_usage.structured_query.v1`,
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

    // Generate deterministic hourly records for every day in timeframe
    const allHourlyRows = [];
    const current = new Date(start);
    while (current <= end) {
      const dateString = current.toISOString().split('T')[0];
      for (let hour = 0; hour < 24; hour++) {
        allHourlyRows.push(getHourlyMockRecord(platform, dateString, hour));
      }
      current.setDate(current.getDate() + 1);
    }

    let responseRows = [];

    // Aggregate based on dimensions
    if (dimensions.includes('date') && dimensions.includes('hour')) {
      // 1. Grouping by both Date and Hour (wellness assessment / heatmap)
      responseRows = allHourlyRows;
    } else if (dimensions.includes('date')) {
      // 2. Grouping by Date (timeline allocation)
      const dateGroups: { [date: string]: { estimated_watch_seconds: number, event_count: number } } = {};
      allHourlyRows.forEach(row => {
        if (!dateGroups[row.date]) {
          dateGroups[row.date] = { estimated_watch_seconds: 0, event_count: 0 };
        }
        dateGroups[row.date].estimated_watch_seconds += row.estimated_watch_seconds;
        dateGroups[row.date].event_count += row.event_count;
      });
      responseRows = Object.keys(dateGroups).sort().map(dateStr => ({
        date: dateStr,
        estimated_watch_seconds: dateGroups[dateStr].estimated_watch_seconds,
        event_count: dateGroups[dateStr].event_count
      }));
    } else if (dimensions.includes('hour')) {
      // 3. Grouping by Hour (heatmap daily averages)
      const hourGroups: { [hour: number]: { estimated_watch_seconds: number, event_count: number } } = {};
      for (let h = 0; h < 24; h++) {
        hourGroups[h] = { estimated_watch_seconds: 0, event_count: 0 };
      }
      allHourlyRows.forEach(row => {
        hourGroups[row.hour].estimated_watch_seconds += row.estimated_watch_seconds;
        hourGroups[row.hour].event_count += row.event_count;
      });
      responseRows = Object.keys(hourGroups).map(Number).sort((a,b) => a - b).map(h => ({
        hour: h,
        estimated_watch_seconds: hourGroups[h].estimated_watch_seconds,
        event_count: hourGroups[h].event_count
      }));
    }

    return new Response(
      JSON.stringify({
        schema_version: `${platform}_usage.structured_query.v1`,
        dataset,
        ldihk_id: ldihkId,
        query: body,
        rows: responseRows,
      }),
      {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
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
