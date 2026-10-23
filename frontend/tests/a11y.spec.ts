import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('WCAG AA accessibility audit with axe-core', async ({ page }) => {
  await page.goto('http://localhost:3000'); // adjust if dev server runs elsewhere
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2aa', 'wcag21aa'])
    .analyze();
  // Log violations for debugging
  console.log('Axe violations:', JSON.stringify(results.violations, null, 2));
  expect(results.violations).toEqual([]);
});
