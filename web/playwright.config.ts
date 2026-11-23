import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  use: {
    baseURL: process.env.CHATFLOW_WEB ?? 'http://127.0.0.1:5173',
    browserName: 'chromium',
    channel: process.env.CHATFLOW_BROWSER_CHANNEL || undefined,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile-320', use: { viewport: { width: 320, height: 720 }, isMobile: true, hasTouch: true } },
    { name: 'mobile-390', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
})
