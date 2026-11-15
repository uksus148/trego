import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.ts',
  workers: 1,
  retries: 0,
  timeout: 30_000,
  outputDir: '../../api/target/fixture-e2e/browser',
  reporter: [['list'], ['json', { outputFile: '../../api/target/fixture-e2e/browser-results.json' }]],
  // Synthetic inputs only. No trace/video: they can inadvertently retain future private inputs.
  use: { headless: true, viewport: { width: 1440, height: 1000 },
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
})
