import { expect, test } from '@playwright/test'

// Financial-services flow: trade request -> pre-trade risk gate -> routing approval.
// The order clears the mandatory risk gate (seeded limits/suitability), so its
// consequential routing is held in the default-deny queue for trader sign-off;
// a blocked order would surface nothing to approve.
test('a cleared trade is held for routing approval and then approved', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Trading' }).click()

  await expect(page.getByRole('heading', { name: /Sales & Trading/i })).toBeVisible()

  // Submit the order through the desk blotter.
  await page.getByRole('button', { name: /submit order/i }).click()

  // Gate PASS -> routing surfaces as a default-deny approval (not auto-executed).
  const request = page.getByRole('button', { name: /markets_route_order/i })
  await expect(request).toBeVisible({ timeout: 15_000 })

  // Trader approves the held routing.
  await request.click()
  const drawer = page.getByRole('dialog', { name: /approval/i })
  await expect(drawer).toBeVisible()
  await drawer.getByLabel(/approver/i).fill('trader@firm')
  await drawer.getByRole('button', { name: /^approve$/i }).click()

  // Approved -> the routing request clears from the pending queue.
  await expect(page.getByText(/no routing approvals pending/i)).toBeVisible({ timeout: 15_000 })
})
