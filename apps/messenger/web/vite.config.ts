import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    port: 5174,
    proxy: { '/v1': { target: process.env.MESSENGER_API ?? 'http://127.0.0.1:8001', ws: true } },
  },
})
