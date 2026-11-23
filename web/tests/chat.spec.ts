import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'

test('register, stream, reload history, rename and delete', async ({ page }, info) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create an account' }).click()
  await page.getByLabel('Email').fill(randomUUID() + '@example.test')
  await page.getByLabel('Password').fill('playwright-only-password')
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  await expect(page.getByText('Mock active')).toBeVisible()
  await page.getByRole('main').getByRole('button', { name: 'New conversation' }).click()
  await page.getByRole('button', { name: 'Rename', exact: true }).click()
  await page.getByLabel('Conversation title').fill('Streaming verification')
  await page.getByRole('button', { name: 'Save' }).click()
  let interrupted = false
  await page.route('**/events?after=*', async route => {
    if (!interrupted) { interrupted = true; return route.abort() }
    return route.continue()
  })
  await page.getByLabel('Message', { exact: true }).fill('Check the flow on ' + info.project.name)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText(/Mock reply for turn 1/)).toBeVisible()
  await expect(page.getByText(/Tell me which part to explore next/)).toBeVisible()
  expect(interrupted).toBe(true)
  await expect(page.getByRole('status')).toHaveCount(0)
  await expect(page).toHaveURL(/\/c\/[\da-f-]+$/i)
  const deepLink = page.url()
  await page.goto(deepLink)
  await expect(page.getByRole('heading', { name: 'Streaming verification' })).toBeVisible()
  await expect(page.getByText(/Mock reply for turn 1/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
  await page.screenshot({ path: info.outputPath('chat.png') })
  if (info.project.name.startsWith('mobile-')) {
    await page.getByRole('button', { name: 'Open conversations' }).click()
    await expect(page.getByRole('navigation', { name: 'Conversation history' })).toBeVisible()
    await page.getByRole('button', { name: 'Close conversations' }).click()
  }
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('button', { name: 'Delete conversation' }).click()
  await expect(page.getByRole('heading', { name: 'Start a conversation' })).toBeVisible()
})
