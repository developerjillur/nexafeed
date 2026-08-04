const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  testMatch: 'browser_video_actions.spec.js',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python3 -m http.server 8765 --bind 127.0.0.1',
    url: 'http://127.0.0.1:8765/index.html',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
