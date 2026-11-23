import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  timeout: 45000,
  expect: { timeout: 12000 },
  use: {
    baseURL: process.env.MESSENGER_WEB ?? 'http://127.0.0.1:5174',
    channel: process.env.CHATFLOW_BROWSER_CHANNEL || undefined,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
})
