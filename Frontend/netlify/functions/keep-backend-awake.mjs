// Keeps the free Render backend from falling asleep during the day, so the
// first visitor does not wait 30-60 s for a cold start. Render stops a free
// service after 15 minutes without requests; this pings every 10 minutes from
// 06:00 to 22:59 UTC (about 540 instance hours a month, inside Render's 750
// free hours) and lets it sleep at night.
//
// Netlify runs scheduled functions on the published production deploy only,
// so this starts working once the change is released to main. It calls the
// site's own /api/wake route, which knows the backend URL and does nothing in
// mock mode. Cost: about 6,000 short invocations a month on the free plan.

export default async () => {
  const site = process.env.URL;
  if (!site) return new Response('no site URL', { status: 500 });
  try {
    const response = await fetch(`${site}/api/wake`, {
      headers: { 'Cache-Control': 'no-store' },
      signal: AbortSignal.timeout(20_000),
    });
    const body = await response.text();
    console.log(`wake: HTTP ${response.status} ${body.slice(0, 80)}`);
  } catch (error) {
    console.log(`wake failed: ${error instanceof Error ? error.message : error}`);
  }
  return new Response('ok');
};

export const config = {
  schedule: '*/10 6-22 * * *',
};
