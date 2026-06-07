import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import { configuredBackendApiBase, isMockApiMode, shouldAllowImplicitMockApiMode } from '../../lib/env';

export const prerender = false;

// Rational approximation of the inverse CDF of the normal distribution (Z-score from percentile)
const getZScore = (p: number): number => {
  const pVal = Math.max(0.01, Math.min(0.99, p / 100));
  const t = Math.sqrt(-2.0 * Math.log(pVal < 0.5 ? pVal : 1.0 - pVal));
  const z = t - ((2.515517 + 0.802853 * t + 0.010328 * t * t) /
                (1.0 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t));
  return pVal < 0.5 ? -z : z;
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

function getPopulationHourlySeconds(platform: string, hour: number, isWeekend: boolean = false) {
  let hourWeight = 1.0;
  if (platform === 'youtube') {
    if (hour >= 23 || hour <= 4) {
      hourWeight = isWeekend ? (hour === 23 || hour === 0 ? 1.9 : 0.9) : (hour === 23 || hour === 0 ? 0.7 : 0.15);
    } else if (hour >= 5 && hour <= 8) {
      hourWeight = 0.1;
    } else if (hour >= 9 && hour <= 12) {
      hourWeight = 0.65;
    } else if (hour >= 13 && hour <= 17) {
      hourWeight = 1.1;
    } else if (hour >= 18 && hour <= 22) {
      hourWeight = 2.4;
    }
    const baseSeconds = 850;
    return baseSeconds * hourWeight * 0.6;
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
    const baseSeconds = 420;
    return baseSeconds * hourWeight * 0.6;
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
    const baseSeconds = 630;
    return baseSeconds * hourWeight * 0.6;
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
    const baseSeconds = 540;
    return baseSeconds * hourWeight * 0.6;
  } else {
    return 100 * 0.6;
  }
}

function isYoutubeOnlyPopulationRequest(platforms: unknown) {
  if (platforms === undefined || platforms === null) return true;
  if (!Array.isArray(platforms) || platforms.length === 0) return false;

  const normalizedPlatforms = new Set(
    platforms
      .filter((platform): platform is string => typeof platform === 'string')
      .map((platform) => platform.trim().toLowerCase())
      .filter(Boolean)
  );

  return normalizedPlatforms.size === 1 && normalizedPlatforms.has('youtube');
}

async function tryBackendPopulation(body: any, authHeader: string): Promise<Response | null> {
  if (!configuredBackendApiBase || !isYoutubeOnlyPopulationRequest(body?.platforms)) {
    return null;
  }

  try {
    const backendResponse = await fetch(`${configuredBackendApiBase}/api/population`, {
      method: 'POST',
      headers: {
        Authorization: authHeader,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...body,
        platforms: ['youtube'],
      }),
    });

    if (backendResponse.status === 404 || backendResponse.status === 405) {
      return null;
    }

    const contentType = backendResponse.headers.get('Content-Type') || 'application/json';
    const responseBody = await backendResponse.text();
    let normalizedBody = responseBody;
    if (contentType.includes('application/json')) {
      try {
        const parsedBody = JSON.parse(responseBody);
        normalizedBody = JSON.stringify({
          ...parsedBody,
          includeSynthetic: parsedBody.includeSynthetic ?? body?.includeSynthetic ?? true,
          hasPopulationData: true,
        });
      } catch (err) {
        normalizedBody = responseBody;
      }
    }

    return new Response(normalizedBody, {
      status: backendResponse.status,
      headers: {
        'Content-Type': contentType,
        'Access-Control-Allow-Origin': '*',
      },
    });
  } catch (err) {
    return null;
  }
}

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
    const backendPopulation = await tryBackendPopulation(body, authHeader);
    if (backendPopulation) {
      return backendPopulation;
    }

    if (!isMockApiMode && !shouldAllowImplicitMockApiMode && !configuredBackendApiBase) {
      return new Response(
        JSON.stringify({
          error: 'population_backend_not_configured',
          message: 'Population mock data is disabled. Configure a backend population API or set PUBLIC_MOCK_API=true.',
        }),
        {
          status: 503,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        }
      );
    }

    // Check if the dataset is ready in mock database
    const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
    let state: any = { datasets: {} };
    try {
      const stateContent = await fs.readFile(statePath, 'utf-8');
      state = JSON.parse(stateContent);
    } catch (err) {
      // Fallback if file doesn't exist
    }

    const isReady = isMockApiMode || !!configuredBackendApiBase || state.datasets?.youtube?.status === 'READY';
    if (!isReady) {
      return new Response(
        JSON.stringify({
          ready: false,
          message: 'Dataset not ready. Please ingest data first.'
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        }
      );
    }

    const {
      platforms = ['youtube'],
      startDate = '2026-05-08',
      endDate = '2026-06-06',
      customPercentile = 90,
      visibleStartDate
    } = body;
    const includeSynthetic = body.includeSynthetic ?? true;

    const actualVisibleStartDate = visibleStartDate || startDate;

    if (!isMockApiMode && configuredBackendApiBase) {
      const backendUrl = configuredBackendApiBase;
      try {
        const backendRes = await fetch(`${backendUrl}/api/population`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': authHeader,
          },
          body: JSON.stringify(body),
        });

        if (backendRes.ok) {
          const backendData = await backendRes.json();
          return new Response(JSON.stringify({
            ...backendData,
            includeSynthetic: backendData.includeSynthetic ?? includeSynthetic,
            hasPopulationData: true,
          }), {
            status: 200,
            headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          });
        }
        console.warn('Backend population API returned non-OK status:', backendRes.status);
      } catch (err) {
        console.warn('Failed to call backend population API:', err);
      }

      // Population API unavailable — still fetch the user's own daily data so
      // the timeline chart can render the user's watch time line.
      try {
        const start = new Date(startDate);
        const end = new Date(endDate);
        const userDailyWatchHours: { [dateStr: string]: number } = {};
        let totalUserSeconds = 0;
        const userHourlySecondsByHour = new Array(24).fill(0);

        // Initialise all dates in range to 0
        const dateInit = new Date(start);
        while (dateInit <= end) {
          userDailyWatchHours[dateInit.toISOString().split('T')[0]] = 0;
          dateInit.setDate(dateInit.getDate() + 1);
        }

        // Fetch daily aggregates from the real backend
        const dailyRes = await fetch(`${backendUrl}/api/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': authHeader },
          body: JSON.stringify({
            dataset: 'youtube_usage',
            metrics: ['estimated_watch_seconds', 'event_count'],
            dimensions: ['date'],
            filters: { start_date: startDate, end_date: endDate },
          }),
        });

        if (dailyRes.ok) {
          const dailyData = await dailyRes.json();
          if (dailyData.rows) {
            dailyData.rows.forEach((row: any) => {
              const dateStr = row.date;
              const secs = row.estimated_watch_seconds || 0;
              userDailyWatchHours[dateStr] = (userDailyWatchHours[dateStr] || 0) + (secs / 3600);
              if (dateStr >= actualVisibleStartDate) totalUserSeconds += secs;
            });
          }
        }

        // Fetch hourly aggregates for the heatmap user column
        const hourlyRes = await fetch(`${backendUrl}/api/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': authHeader },
          body: JSON.stringify({
            dataset: 'youtube_usage',
            metrics: ['estimated_watch_seconds', 'event_count'],
            dimensions: ['hour'],
            filters: { start_date: actualVisibleStartDate, end_date: endDate },
          }),
        });

        if (hourlyRes.ok) {
          const hourlyData = await hourlyRes.json();
          if (hourlyData.rows) {
            hourlyData.rows.forEach((row: any) => {
              const hr = row.hour;
              if (hr >= 0 && hr < 24) userHourlySecondsByHour[hr] += row.estimated_watch_seconds || 0;
            });
          }
        }

        const [y1, m1, d1] = actualVisibleStartDate.split('-').map(Number);
        const [y2, m2, d2] = endDate.split('-').map(Number);
        const dayCount = Math.max(1, Math.round(
          (Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / (1000 * 3600 * 24)
        ) + 1);

        const userDailyAverageHours = totalUserSeconds / 3600 / dayCount;
        const userHourlyAverages = userHourlySecondsByHour.map(s => s / dayCount);

        // Build deciles with user hours only — no population bands
        const dateList = Object.keys(userDailyWatchHours).sort();
        const deciles = dateList.map(dateStr => ({
          date: dateStr,
          user: parseFloat(userDailyWatchHours[dateStr].toFixed(2)),
          median: null,
          top10: null,
          bottom10: null,
          customPercentileHours: null,
        }));

        // Build hourlyAverages with user data only (no population baseline)
        const hourlyAverages = Array.from({ length: 24 }, (_, hour) => ({
          hour: `${hour.toString().padStart(2, '0')}:00`,
          populationAvg: null,
          userAvg: parseFloat((userHourlyAverages[hour] / 3600).toFixed(3)),
        }));

        return new Response(JSON.stringify({
          ready: true,
          hasPopulationData: false,
          userPercentile: null,
          userDailyAverageHours: parseFloat(userDailyAverageHours.toFixed(2)),
          includeSynthetic: false,
          customPercentile,
          distribution: [],
          deciles,
          hourlyAverages,
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        });
      } catch (fallbackErr) {
        console.error('Failed to fetch user fallback data:', fallbackErr);
        // Last resort: return empty but valid structure
        return new Response(JSON.stringify({
          ready: true,
          hasPopulationData: false,
          userPercentile: null,
          userDailyAverageHours: null,
          includeSynthetic: false,
          customPercentile,
          distribution: [],
          deciles: [],
          hourlyAverages: [],
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        });
      }
    }

    const start = new Date(startDate);
    const end = new Date(endDate);

    const [y1, m1, d1] = actualVisibleStartDate.split('-').map(Number);
    const [y2, m2, d2] = endDate.split('-').map(Number);
    const startUTC = Date.UTC(y1, m1 - 1, d1);
    const endUTC = Date.UTC(y2, m2 - 1, d2);
    const diffMs = endUTC - startUTC;
    const dayCount = Math.max(1, Math.round(diffMs / (1000 * 3600 * 24)) + 1);

    // 1. Calculate user's watch metrics over the range
    let totalUserSeconds = 0;
    const userDailyWatchHours: { [dateStr: string]: number } = {};
    const userHourlySecondsByHour = new Array(24).fill(0);

    // Initialize every date in range to 0 to ensure full timeline coverage
    const dateInit = new Date(start);
    while (dateInit <= end) {
      const dateString = dateInit.toISOString().split('T')[0];
      userDailyWatchHours[dateString] = 0;
      dateInit.setDate(dateInit.getDate() + 1);
    }

    if (isMockApiMode || !configuredBackendApiBase) {
      const current = new Date(start);
      while (current <= end) {
        const dateString = current.toISOString().split('T')[0];
        let dailySecs = 0;
        for (let hour = 0; hour < 24; hour++) {
          let hourSecs = 0;
          platforms.forEach((platform: string) => {
            const record = getHourlyMockRecord(platform, dateString, hour);
            hourSecs += record.estimated_watch_seconds;
          });
          dailySecs += hourSecs;
          if (dateString >= actualVisibleStartDate) {
            userHourlySecondsByHour[hour] += hourSecs;
          }
        }
        userDailyWatchHours[dateString] = dailySecs / 3600;
        if (dateString >= actualVisibleStartDate) {
          totalUserSeconds += dailySecs;
        }

        current.setDate(current.getDate() + 1);
      }
    } else {
      // Query the real backend API for the user's actual data!
      const backendUrl = configuredBackendApiBase;

      // We query each platform, but since the Python backend only supports 'youtube_usage', we filter.
      for (const platform of platforms) {
        if (platform !== 'youtube') continue; // Skip non-supported platforms in backend database

        // 1. Fetch daily watch seconds.
        const dailyRes = await fetch(`${backendUrl}/api/query`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': authHeader,
          },
          body: JSON.stringify({
            dataset: 'youtube_usage',
            metrics: ['estimated_watch_seconds', 'event_count'],
            dimensions: ['date'],
            filters: {
              start_date: startDate,
              end_date: endDate,
            },
          }),
        });

        if (!dailyRes.ok) {
          throw new Error(`Failed to fetch daily data from backend for ${platform}`);
        }

        const dailyData = await dailyRes.json();
        if (dailyData.rows) {
          dailyData.rows.forEach((row: any) => {
            const dateStr = row.date;
            const secs = row.estimated_watch_seconds || 0;
            userDailyWatchHours[dateStr] = (userDailyWatchHours[dateStr] || 0) + (secs / 3600);

            if (dateStr >= actualVisibleStartDate) {
              totalUserSeconds += secs;
            }
          });
        }

        // 2. Fetch hourly watch seconds (visible range only!)
        const hourlyRes = await fetch(`${backendUrl}/api/query`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': authHeader,
          },
          body: JSON.stringify({
            dataset: 'youtube_usage',
            metrics: ['estimated_watch_seconds', 'event_count'],
            dimensions: ['hour'],
            filters: {
              start_date: actualVisibleStartDate,
              end_date: endDate,
            },
          }),
        });

        if (!hourlyRes.ok) {
          throw new Error(`Failed to fetch hourly data from backend for ${platform}`);
        }

        const hourlyData = await hourlyRes.json();
        if (hourlyData.rows) {
          hourlyData.rows.forEach((row: any) => {
            const hr = row.hour;
            const secs = row.estimated_watch_seconds || 0;
            if (hr >= 0 && hr < 24) {
              userHourlySecondsByHour[hr] += secs;
            }
          });
        }
      }
    }

    const userDailyAverageHours = totalUserSeconds / 3600 / dayCount;
    const userHourlyAverages = userHourlySecondsByHour.map(s => s / dayCount);

    // Dynamic statistical scaling parameters per platform
    const platformMeans: Record<string, number> = {
      youtube: 2.4,
      instagram: 1.2,
      tiktok: 1.8,
      spotify: 1.5,
      twitter: 0.8,
      linkedin: 0.4
    };
    const platformStdDevs: Record<string, number> = {
      youtube: 1.2,
      instagram: 0.6,
      tiktok: 0.9,
      spotify: 0.75,
      twitter: 0.4,
      linkedin: 0.2
    };

    // Combine means and standard deviations (sum of variances for standard dev)
    const combinedMean = platforms.reduce((sum, p) => sum + (platformMeans[p] || 0.5), 0);
    const combinedVariance = platforms.reduce((sum, p) => sum + Math.pow(platformStdDevs[p] || 0.3, 2), 0);
    const combinedStdDev = Math.sqrt(combinedVariance);

    const scaleFactor = combinedMean / 2.4;
    const otherUsersDailyAverages = [1.1 * scaleFactor, 2.0 * scaleFactor, 5.1 * scaleFactor];

    // Response components
    let distribution = [];
    let deciles = [];
    let hourlyAverages = [];
    let userPercentile = 50;

    if (includeSynthetic) {
      // SYNTHETIC MODE - Scale visual range based on mean
      const binWidth = Math.max(0.1, parseFloat((combinedMean * 3.5 / 40).toFixed(2)));
      for (let i = 0; i <= 40; i++) {
        const hours = i * binWidth;
        const density = 1000 * Math.exp(-0.5 * Math.pow((hours - combinedMean) / combinedStdDev, 2)) / (combinedStdDev * Math.sqrt(2 * Math.PI));
        distribution.push({
          hours: parseFloat(hours.toFixed(1)),
          density: Math.max(0, Math.round(density)),
        });
      }

      // Calculate user percentile ranking based on standard normal CDF
      const z = (userDailyAverageHours - combinedMean) / combinedStdDev;
      const t = 1.0 / (1.0 + 0.2316419 * Math.abs(z));
      const dVal = 0.3989423 * Math.exp(-z * z / 2.0);
      let prob = 1.0 - dVal * ((((1.330274429 * t - 1.821255978) * t + 1.781477937) * t - 0.356563782) * t + 0.31938153) * t;
      if (z < 0) prob = 1.0 - prob;
      userPercentile = Math.round(prob * 100);

      // Timeline cohorts (deciles) and custom percentile line
      const zScoreCustom = getZScore(customPercentile);
      const dateList = Object.keys(userDailyWatchHours).sort();
      deciles = dateList.map(dateStr => {
        const uHours = userDailyWatchHours[dateStr];

        const dObj = new Date(dateStr);
        const dayOfWeek = dObj.getDay();
        const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
        const weekendMult = isWeekend ? 1.45 : 0.95;

        const epochDays = Math.round((dObj.getTime() - new Date('2016-01-01').getTime()) / (1000 * 3600 * 24));
        const seasonalTrend = 1.0 + Math.sin(epochDays / 120) * 0.25;

        // Calculate independent dynamic mean and standard deviation for this date
        const dateMean = combinedMean * weekendMult * seasonalTrend;
        const dateStdDev = combinedStdDev * weekendMult * seasonalTrend;

        const median = parseFloat(dateMean.toFixed(2));
        const top10 = parseFloat((dateMean + 1.282 * dateStdDev).toFixed(2));
        const bottom10 = parseFloat(Math.max(0, dateMean - 1.282 * dateStdDev).toFixed(2));
        const customHours = parseFloat(Math.max(0, dateMean + zScoreCustom * dateStdDev).toFixed(2));

        return {
          date: dateStr,
          user: parseFloat(uHours.toFixed(2)),
          median,
          top10,
          bottom10,
          customPercentileHours: customHours,
        };
      });

      // Hourly watch profile averages
      for (let hour = 0; hour < 24; hour++) {
        let popSecs = 0;
        platforms.forEach((platform: string) => {
          popSecs += getPopulationHourlySeconds(platform, hour, false);
        });

        hourlyAverages.push({
          hour: `${hour.toString().padStart(2, '0')}:00`,
          populationAvg: parseFloat((popSecs / 3600).toFixed(3)),
          userAvg: parseFloat((userHourlyAverages[hour] / 3600).toFixed(3)),
        });
      }

    } else {
      // ACTUAL MODE
      const allAverages = [...otherUsersDailyAverages, userDailyAverageHours].sort((a, b) => a - b);
      const userIndex = allAverages.indexOf(userDailyAverageHours);
      userPercentile = Math.round(((userIndex + 1) / 4) * 100);

      // Create a histogram distribution with 10 bins representing the 4 actual users
      const binWidth = Math.max(0.2, parseFloat((combinedMean * 2 / 10).toFixed(1)));
      for (let i = 0; i <= 10; i++) {
        const hoursMin = i * binWidth;
        const hoursMax = (i + 1) * binWidth;
        const count = allAverages.filter(avg => avg >= hoursMin && avg < hoursMax).length;
        distribution.push({
          hours: parseFloat(((hoursMin + hoursMax) / 2).toFixed(1)),
          density: count,
        });
      }

      // Timeline cohorts based on actual 4 users
      const dateList = Object.keys(userDailyWatchHours).sort();
      deciles = dateList.map(dateStr => {
        const uHours = userDailyWatchHours[dateStr];

        const d = new Date(dateStr);
        const dayOfWeek = d.getDay();
        const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
        const baseHoursMultiplier = isWeekend ? 1.5 : 1.0;
        const dateNum = d.getDate();
        const trend = 1 + (dateNum / 30) * 0.2;

        const pseudo1 = Math.sin(d.getTime() + 5) * 0.2 + 1;
        const pseudo2 = Math.sin(d.getTime() + 20) * 0.15 + 1;
        const pseudo3 = Math.sin(d.getTime() + 45) * 0.3 + 1;

        const u1Hours = 1.1 * scaleFactor * baseHoursMultiplier * trend * pseudo1;
        const u2Hours = 2.0 * scaleFactor * baseHoursMultiplier * trend * pseudo2;
        const u3Hours = 5.1 * scaleFactor * baseHoursMultiplier * trend * pseudo3;

        const dailySorted = [u1Hours, u2Hours, u3Hours, uHours].sort((a, b) => a - b);

        const bottom10 = parseFloat(dailySorted[0].toFixed(2));
        const median = parseFloat(((dailySorted[1] + dailySorted[2]) / 2).toFixed(2));
        const top10 = parseFloat(dailySorted[3].toFixed(2));

        const idx = (customPercentile / 100) * (dailySorted.length - 1);
        const lower = Math.floor(idx);
        const upper = Math.ceil(idx);
        const weight = idx - lower;
        const customHours = dailySorted[lower] * (1 - weight) + dailySorted[upper] * weight;

        return {
          date: dateStr,
          user: parseFloat(uHours.toFixed(2)),
          median,
          top10,
          bottom10,
          customPercentileHours: parseFloat(customHours.toFixed(2)),
        };
      });

      // Hourly watch averages
      for (let hour = 0; hour < 24; hour++) {
        let popSecs = 0;
        platforms.forEach((platform: string) => {
          popSecs += getPopulationHourlySeconds(platform, hour, false);
        });

        const userAvgHrs = userHourlyAverages[hour] / 3600;
        const u1AvgHrs = (popSecs / 3600) * 0.45;
        const u2AvgHrs = (popSecs / 3600) * 0.85;
        const u3AvgHrs = (popSecs / 3600) * 2.1;

        const populationAvgHrs = (u1AvgHrs + u2AvgHrs + u3AvgHrs + userAvgHrs) / 4;

        hourlyAverages.push({
          hour: `${hour.toString().padStart(2, '0')}:00`,
          populationAvg: parseFloat(populationAvgHrs.toFixed(3)),
          userAvg: parseFloat(userAvgHrs.toFixed(3)),
        });
      }
    }

    return new Response(
      JSON.stringify({
        schema_version: 'youtube_usage.population.mock.v1',
        ready: true,
        dataset: 'youtube_usage',
        platforms,
        userPercentile,
        userDailyAverageHours: parseFloat(userDailyAverageHours.toFixed(2)),
        includeSynthetic,
        customPercentile,
        distribution,
        deciles,
        hourlyAverages,
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
    console.error('Population endpoint error:', err);
    return new Response(JSON.stringify({ error: 'internal_error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
};
