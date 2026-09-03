import { expect, test } from '@playwright/test';

test('marketing navigation and pricing content are available', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Platform' })).toBeVisible();
  await page.getByRole('link', { name: 'Pricing' }).click();
  await expect(page).toHaveURL(/\/pricing$/);
  await expect(page.getByRole('heading', { name: 'Choose the right place to start.' })).toBeVisible();
  await expect(page.getByText('₹300 / month')).toBeVisible();
});

test('docs page exposes guide sections without requiring authentication', async ({ page }) => {
  await page.goto('/docs');
  await expect(page.getByRole('heading', { name: 'Understand the code before you change it.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Introduction' }).first()).toBeVisible();
});
