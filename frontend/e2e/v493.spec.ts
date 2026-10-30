import { expect, test } from '@playwright/test';
import { mockApi, signIn } from './fixtures/v43';

for (const width of [375, 1440]) {
  for (const regime of ['RELIEF_RALLY', 'EMERGING_RECOVERY', 'UNKNOWN']) {
    test(`Stage-aware learning ${regime} at ${width}px`, async ({ page }) => {
      await mockApi(page);
      await page.setViewportSize({ width, height: 1000 });
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      const timeframes = { '5': { trend: 'BULLISH' }, '15': { trend: 'BULLISH' }, '60': { trend: 'BEARISH' }, '240': { trend: 'UNKNOWN' } };
      await page.route('**/api/personal-paper/learning', route => route.fulfill({ json: {
        status: 'INSUFFICIENT_EVIDENCE', backend_version: '4.9.3-rc.1', approved_execution_profile: '4.9.3-paper.1',
        approved_model: 'DETERMINISTIC_FROZEN_BASELINE_NO_APPROVED_ML',
        dataset: { counts: { LABELED: 12, PENDING: 4 }, independent_episodes: 4, required_episodes: 240, required_days: 45 },
        legacy_dataset: { counts: { DATA_QUALITY_FAILED: 40235, LABELED: 141 } },
        funnel: { unique_signals: 7500, priced_plans: 88, stages: { TECHNICAL_REJECTED: 7200, TECHNICAL_VALID_UNPRICED: 22, ECONOMICS_REJECTED: 15 },
          dispositions: { OBSERVED: 7500, DATA_QUALITY_FAILED: 0, COVERAGE_EXCLUDED: 23000 },
          latest: [{ observed_at: new Date().toISOString(), stage: 'PRIMARY_ADMISSION_REJECTED',
            market_state: { state: regime, reason: 'Short-term improvement requires confirmation', timeframes,
              benchmarks: { 'BTC-EUR': { timeframes, return_30m: '.002' }, 'ETH-EUR': { timeframes, return_30m: '.001' } } },
            primary_admission: { gates: { primary_macro_context: false, primary_local_reclaim: true } } }] },
        market_task: { counts: { LABELED: 5100, PENDING: 2400 }, independent_episodes: 4,
          latest_training: { status: 'INSUFFICIENT_EVIDENCE' }, active_challenger: null, forward_episodes: 0 },
        provider_measurements: { 'market_window:1': { started_at: new Date().toISOString(), observed_until: new Date().toISOString(), request_success: 500, request_429: 2, coalesced_read: 10 } },
        observed_at: new Date().toISOString(), collector_stale: false, warnings: [],
        primary_promotion_automatic: false, live_authorized: false
      } }));
      await signIn(page);
      await page.getByRole('button', { name: 'Research', exact: true }).click();
      const panel = page.getByLabel('Learning and Performance');
      await expect(panel.getByText('Backend 4.9.3-rc.1 · Execution profile 4.9.3-paper.1')).toBeVisible();
      await expect(panel.getByRole('heading', { name: regime.replaceAll('_', ' ') })).toBeVisible();
      await expect(panel.getByRole('heading', { name: 'Observation funnel' })).toBeVisible();
      await expect(panel.getByText(/Blocking admission gates: primary macro context/)).toBeVisible();
      await expect(panel.getByRole('table', { name: 'Benchmark timeframe context' })).toBeVisible();
      await expect(panel.getByRole('table', { name: 'Provider measurement windows' })).toBeVisible();
      await expect(panel.getByText(/They have no assumed entry, execution costs or achievable profit/)).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
      await page.screenshot({ path: `${process.env.AUTOTRADER_BROWSER_EVIDENCE}/v493-${regime}-${width}.png`, fullPage: true });
    });
  }
}
