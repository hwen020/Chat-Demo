import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 45000,
  expect: { timeout: 12000 },
  workers: 1,
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  use: {
    baseURL: process.env.MESSENGER_WEB ?? 'http://127.0.0.1:5174',
    channel: process.env.CHATFLOW_BROWSER_CHANNEL || undefined,
    trace: 'retain-on-failure',
  },
})
