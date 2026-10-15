import { expect, test, type Page } from '@playwright/test';
import { configure, TextReader, Uint8ArrayWriter, ZipWriter } from '@zip.js/zip.js';

configure({ useWebWorkers: false });

/** A minimal Google Takeout export with recent YouTube watch history. */
async function takeoutZip(watchCount: number): Promise<Buffer> {
  const now = Date.now();
  const records = Array.from({ length: watchCount }, (_, index) => {
    const id = `e2e${String(index).padStart(8, '0')}`;
    return {
      header: 'YouTube',
      title: `Watched E2E video ${index}`,
      titleUrl: `https://www.youtube.com/watch?v=${id}`,
      subtitles: [{ name: `Channel ${index % 5}`, url: `https://www.youtube.com/channel/UCe2e${index % 5}` }],
      // Spread over the last ~10 days, newest two hours ago.
      time: new Date(now - 2 * 3600_000 - index * 47 * 60_000).toISOString(),
      products: ['YouTube'],
    };
  });
  const writer = new ZipWriter(new Uint8ArrayWriter());
  await writer.add(
    'Takeout/YouTube and YouTube Music/history/watch-history.json',
    new TextReader(JSON.stringify(records))
  );
  return Buffer.from(await writer.close());
}

/** Uploads an export from the login screen and returns the generated LDiHK-ID. */
async function uploadNewWorkspace(page: Page): Promise<string> {
  await page.goto('/dashboard');
  await expect(page.getByRole('heading', { name: 'Initialize Workspace' })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: 'takeout-e2e.zip',
    mimeType: 'application/zip',
    buffer: await takeoutZip(300),
  });
  await page.getByRole('button', { name: 'Agree & Upload' }).click();

  const idModal = page.getByRole('heading', { name: 'Your LDiHK-ID is Ready' });
  await expect(idModal).toBeVisible();
  const ldihkId = (await page.locator('span.select-all').innerText()).trim();
  expect(ldihkId).toMatch(/^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$/);
  await page.getByRole('button', { name: "I've Saved It, Start Ingestion" }).click();
  return ldihkId;
}

test('upload, dashboards, population comparison and deletion', async ({ page }) => {
  const ldihkId = await uploadNewWorkspace(page);

  // The import runs in the API process; the console polls until it is done.
  await expect(page.getByText('Active', { exact: true })).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole('heading', { name: 'Daily Watchtime Allocation' })).toBeVisible();
  await expect(page.getByText('No Data Available')).toHaveCount(0);

  // Population: the seeded synthetic profiles act as the comparison group.
  await page.locator('#tab-population-benchmark').click();
  await expect(page).toHaveURL(/\/population/);
  await expect(page.getByText('Population Comparison Active')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Compared with \d+ other people/)).toBeVisible();

  // Signing in again with the ID restores the workspace.
  await page.getByRole('button', { name: /Log Out/ }).click();
  await page.getByPlaceholder(/ldihk-/).fill(ldihkId);
  await page.getByRole('button', { name: 'Access Dashboard' }).click();
  await expect(page.getByText('Active', { exact: true })).toBeVisible({ timeout: 60_000 });

  // Deleting needs the ID typed in, then the ID stops working.
  await page.getByRole('button', { name: 'Delete My Data' }).click();
  const confirmDelete = page.getByRole('button', { name: 'Delete permanently' });
  await expect(confirmDelete).toBeDisabled();
  await page.getByRole('dialog').getByRole('textbox').fill(ldihkId);
  await confirmDelete.click();
  await expect(page.getByText(/Your data has been deleted/)).toBeVisible();

  await page.getByPlaceholder(/ldihk-/).fill(ldihkId);
  await page.getByRole('button', { name: 'Access Dashboard' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Access Your Console' })).toBeVisible();
});
