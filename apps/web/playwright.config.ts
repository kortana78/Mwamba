import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 120_000,
  fullyParallel: false,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'python -m uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/health',
      timeout: 60_000,
      reuseExistingServer: true,
    },
    {
      command: 'node node_modules/vite/bin/vite.js --port 5173 --host 127.0.0.1',
      url: 'http://127.0.0.1:5173/',
      timeout: 60_000,
      reuseExistingServer: true,
    },
  ],
});
