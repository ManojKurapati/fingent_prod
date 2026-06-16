import { expect, test } from '@playwright/test'

// Enterprise flow: FP&A forecast -> variance commentary approval -> report.
// Runs a forecast through the real UI; a breaching cost centre raises a
// human-in-the-loop commentary request that a manager approves.
test('FP&A forecast surfaces a commentary approval that a manager approves', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'FP&A' }).click()

  await expect(page.getByRole('heading', { name: /FP&A Planning/i })).toBeVisible()

  // Run the planning fan-out.
  await page.getByRole('button', { name: /run forecast/i }).click()

  // The seeded cc1 breaches its variance threshold -> a commentary request appears.
  const request = page.getByRole('button', { name: /fpa_request_commentary/i })
  await expect(request).toBeVisible({ timeout: 15_000 })

  // Open the approval drawer and approve it (human-in-the-loop).
  await request.click()
  const drawer = page.getByRole('dialog', { name: /approval/i })
  await expect(drawer).toBeVisible()
  await drawer.getByLabel(/approver/i).fill('fpa.manager@firm')
  await drawer.getByRole('button', { name: /^approve$/i }).click()

  // Approved -> it clears from the pending commentary queue (the report is final).
  await expect(page.getByText(/no commentary requests/i)).toBeVisible({ timeout: 15_000 })
})
