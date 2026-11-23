import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.mjs',
  timeout: 30000,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:4399/', browserName: 'chromium' },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: {
    command: 'python3 -m http.server 4399 --bind 127.0.0.1 --directory ../docs',
    stdout: 'ignore',
    stderr: 'ignore',
    url: 'http://127.0.0.1:4399/',
    reuseExistingServer: !process.env.CI,
  },
});
