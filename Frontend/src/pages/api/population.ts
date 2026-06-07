import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';

export const prerender = false;

// Rational approximation of the inverse CDF of the normal distribution (Z-score from percentile)
const getZScore = (p: number): number => {
  const pVal = Math.max(0.01, Math.min(0.99, p / 100));
  const t = Math.sqrt(-2.0 * Math.log(pVal < 0.5 ? pVal : 1.0 - pVal));
  const z = t - ((2.515517 + 0.802853 * t + 0.010328 * t * t) / 
                (1.0 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t));
  return pVal < 0.5 ? -z : z;
};

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

    // Check if the dataset is ready in mock database
    const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
    let state: any = { datasets: {} };
    try {
      const stateContent = await fs.readFile(statePath, 'utf-8');
      state = JSON.parse(stateContent);
    } catch (err) {
      // Fallback if file doesn't exist
    }

    const isYoutubeReady = state.datasets?.youtube?.status === 'READY';
    if (!isYoutubeReady) {
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

    const body = await request.json();
    const { 
      startDate = '2026-05-08', 
      endDate = '2026-06-06', 
      useSyntheticData = true,
      customPercentile = 90
    } = body;

    const start = new Date(startDate);
    const end = new Date(endDate);

    const [y1, m1, d1] = startDate.split('-').map(Number);
    const [y2, m2, d2] = endDate.split('-').map(Number);
    const startUTC = Date.UTC(y1, m1 - 1, d1);
    const endUTC = Date.UTC(y2, m2 - 1, d2);
    const diffMs = endUTC - startUTC;
    const dayCount = Math.max(1, Math.round(diffMs / (1000 * 3600 * 24)) + 1);

    // 1. Calculate user's deterministic watch metrics over the range
    let totalUserSeconds = 0;
    const userDailyWatchHours: { [dateStr: string]: number } = {};
    const userHourlySecondsByHour = new Array(24).fill(0);

    const current = new Date(start);
    while (current <= end) {
      const dateString = current.toISOString().split('T')[0];
      const dayOfWeek = current.getDay();
      const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;

      const baseHoursMultiplier = isWeekend ? 1.5 : 1.0;
      const d = current.getDate();
      const trend = 1 + (d / 30) * 0.2;
      const avgHours = 2.4;

      const pseudoRandDate = Math.sin(current.getTime() + 12) * 0.25 + 1;
      const watchHours = Math.max(0, avgHours * baseHoursMultiplier * trend * pseudoRandDate);
      userDailyWatchHours[dateString] = watchHours;
      totalUserSeconds += Math.round(watchHours * 3600);

      // Hourly calculations for the heatmap
      for (let hour = 0; hour < 24; hour++) {
        let weight = 1;
        if (hour >= 1 && hour <= 5) weight = 0.1;
        else if (hour >= 8 && hour <= 11) weight = 1.2;
        else if (hour >= 12 && hour <= 17) weight = 1.5;
        else if (hour >= 18 && hour <= 22) weight = 2.8;
        else weight = 1.4;

        const baseSecs = 1200;
        const pseudoRandHour = Math.sin(hour + current.getTime() + 5) * 0.2 + 1;
        const watchSeconds = Math.max(0, Math.round(baseSecs * weight * pseudoRandHour));
        userHourlySecondsByHour[hour] += watchSeconds;
      }

      current.setDate(current.getDate() + 1);
    }

    const userDailyAverageHours = totalUserSeconds / 3600 / dayCount;
    const userHourlyAverages = userHourlySecondsByHour.map(s => s / dayCount);

    // Other users setup
    // User 1: Light user (avg 1.1 hrs/day)
    // User 2: Moderate user (avg 2.0 hrs/day)
    // User 3: Heavy user (avg 5.1 hrs/day)
    const otherUsersDailyAverages = [1.1, 2.0, 5.1];

    // Response components
    let distribution = [];
    let deciles = [];
    let hourlyAverages = [];
    let userPercentile = 50;

    if (useSyntheticData) {
      // SYNTHETIC MODE - Realistic log-normal curve (~10,000 users)
      // Mean = 2.4, StdDev = 1.2
      for (let i = 0; i <= 40; i++) {
        const hours = i * 0.2;
        // Standard normal distribution formula as representation of population distribution
        const density = 1000 * Math.exp(-0.5 * Math.pow((hours - 2.4) / 1.2, 2)) / (1.2 * Math.sqrt(2 * Math.PI));
        distribution.push({
          hours: parseFloat(hours.toFixed(1)),
          density: Math.round(density),
        });
      }

      // Calculate user percentile ranking based on standard normal CDF
      const z = (userDailyAverageHours - 2.4) / 1.2;
      // Approximation of CDF
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
        const median = parseFloat((uHours * 0.9 + Math.sin(new Date(dateStr).getTime()) * 0.15).toFixed(2));
        const top10 = parseFloat((median * 1.8 + 0.6).toFixed(2));
        const bottom10 = parseFloat((median * 0.25).toFixed(2));
        
        // Calculate custom percentile line daily hours
        const customHours = Math.max(0, median + zScoreCustom * 1.2);

        return {
          date: dateStr,
          user: parseFloat(uHours.toFixed(2)),
          median,
          top10,
          bottom10,
          customPercentileHours: parseFloat(customHours.toFixed(2)),
        };
      });

      // Hourly watch profile averages
      for (let hour = 0; hour < 24; hour++) {
        let weight = 1;
        if (hour >= 1 && hour <= 5) weight = 0.12;
        else if (hour >= 8 && hour <= 11) weight = 1.1;
        else if (hour >= 12 && hour <= 17) weight = 1.4;
        else if (hour >= 18 && hour <= 22) weight = 2.6;
        else weight = 1.35;

        // Global population average (seconds)
        const populationAvgSeconds = 1100 * weight;
        
        hourlyAverages.push({
          hour: `${hour.toString().padStart(2, '0')}:00`,
          populationAvg: parseFloat((populationAvgSeconds / 3600).toFixed(3)),
          userAvg: parseFloat((userHourlyAverages[hour] / 3600).toFixed(3)),
        });
      }

    } else {
      // ACTUAL MODE - Only 4 actual users (very small database representation)
      const allAverages = [...otherUsersDailyAverages, userDailyAverageHours].sort((a, b) => a - b);
      const userIndex = allAverages.indexOf(userDailyAverageHours);
      userPercentile = Math.round(((userIndex + 1) / 4) * 100);

      // Create a histogram distribution with 10 bins representing the 4 actual users
      for (let i = 0; i <= 10; i++) {
        const hoursMin = i * 0.8;
        const hoursMax = (i + 1) * 0.8;
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
        
        // Simulating watch hours for the other 3 users on this date
        const d = new Date(dateStr);
        const dayOfWeek = d.getDay();
        const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
        const baseHoursMultiplier = isWeekend ? 1.5 : 1.0;
        const dateNum = d.getDate();
        const trend = 1 + (dateNum / 30) * 0.2;
        
        const pseudo1 = Math.sin(d.getTime() + 5) * 0.2 + 1;
        const pseudo2 = Math.sin(d.getTime() + 20) * 0.15 + 1;
        const pseudo3 = Math.sin(d.getTime() + 45) * 0.3 + 1;

        const u1Hours = 1.1 * baseHoursMultiplier * trend * pseudo1;
        const u2Hours = 2.0 * baseHoursMultiplier * trend * pseudo2;
        const u3Hours = 5.1 * baseHoursMultiplier * trend * pseudo3;

        const dailySorted = [u1Hours, u2Hours, u3Hours, uHours].sort((a, b) => a - b);

        const bottom10 = parseFloat(dailySorted[0].toFixed(2)); // User 1
        const median = parseFloat(((dailySorted[1] + dailySorted[2]) / 2).toFixed(2)); // Avg of User 2 & 4
        const top10 = parseFloat(dailySorted[3].toFixed(2)); // User 3

        // Custom percentile line calculation using linear interpolation of sorted daily values
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

      // Hourly watch averages (noisy averages from 4 actual users)
      const u1HourlyAverages = new Array(24).fill(0);
      const u2HourlyAverages = new Array(24).fill(0);
      const u3HourlyAverages = new Array(24).fill(0);

      for (let hour = 0; hour < 24; hour++) {
        // User 1: mostly morning (8-10)
        let w1 = hour >= 8 && hour <= 10 ? 2.5 : 0.4;
        u1HourlyAverages[hour] = (600 * w1) / 3600;

        // User 2: mostly midday (12-15)
        let w2 = hour >= 12 && hour <= 15 ? 2.2 : 0.6;
        u2HourlyAverages[hour] = (1000 * w2) / 3600;

        // User 3: extreme night viewer (20-23)
        let w3 = hour >= 20 && hour <= 23 ? 3.8 : 0.3;
        u3HourlyAverages[hour] = (2200 * w3) / 3600;

        const userAvgHrs = userHourlyAverages[hour] / 3600;
        const populationAvgHrs = (u1HourlyAverages[hour] + u2HourlyAverages[hour] + u3HourlyAverages[hour] + userAvgHrs) / 4;

        hourlyAverages.push({
          hour: `${hour.toString().padStart(2, '0')}:00`,
          populationAvg: parseFloat(populationAvgHrs.toFixed(3)),
          userAvg: parseFloat(userAvgHrs.toFixed(3)),
        });
      }
    }

    return new Response(
      JSON.stringify({
        ready: true,
        userPercentile,
        userDailyAverageHours: parseFloat(userDailyAverageHours.toFixed(2)),
        useSyntheticData,
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
