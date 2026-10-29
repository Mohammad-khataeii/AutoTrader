import { expect, test } from '@playwright/test';
import { mockApi, signIn } from './fixtures/v43';

for (const width of [375, 1440]) {
  for (const state of ['INSUFFICIENT_EVIDENCE', 'QUALIFIED_SHADOW', 'QUARANTINED', 'STALE']) {
    test(`Learning evidence ${state} at ${width}px`, async ({ page }) => {
      await mockApi(page);
      await page.setViewportSize({ width, height: 1000 });
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/personal-paper/learning', route => route.fulfill({ json: {
        status: state === 'STALE' ? 'COLLECTING' : state, backend_version: '4.9.2-rc.2',
        approved_execution_profile: '4.9.2-paper.1', approved_model: 'DETERMINISTIC_FROZEN_BASELINE_NO_APPROVED_ML',
        dataset: { counts: { LABELED: 81, PENDING: 13, DATA_QUALITY_FAILED: 13412 }, independent_episodes: 4,
          required_episodes: 240, required_days: 45, coverage_failures: { 'Missing causal snapshot': 21 } },
        active_challenger: state === 'QUALIFIED_SHADOW' ? 'a'.repeat(64) : null,
        quarantined_challenger: state === 'QUARANTINED' ? { model_id: 'b'.repeat(64), reason: 'forward_deterioration_or_feature_drift' } : null,
        latest_training: { trained_at: new Date().toISOString(), comparisons: [{ partition: 'untouched_holdout',
          challenger: { episodes: 32, selected: 14, net_expectancy_r: .1, calibration_error: .07, brier: .21 },
          approved_baseline: { net_expectancy_r: -.1 }, cost_stress_2x: { net_expectancy_r: .02 } }] },
        observed_at: new Date().toISOString(), collector_stale: state === 'STALE',
        warnings: state === 'INSUFFICIENT_EVIDENCE' ? ['Insufficient independent evidence for ML promotion'] : [],
        primary_promotion_automatic: false, live_authorized: false,
        rejection_reasons: { primary_local_reclaim: 12 }, forward_evaluation: { selected_independent_episodes: 0 },
        exit_feedback: { modeled_stop_episodes: 2, ambiguous_barrier_episodes: 1, policy: 'Existing stops remain frozen' }
      } }));
      await signIn(page);
      await page.getByRole('button', { name: 'Research', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Evidence before model promotion' })).toBeVisible();
      const panel = page.getByLabel('Learning and Performance');
      await expect(panel.getByText('Backend 4.9.2-rc.2 · Execution profile 4.9.2-paper.1')).toBeVisible();
      await expect(panel.getByText('Shadow research only', { exact: true })).toBeVisible();
      await expect(page.getByRole('table', { name: 'Learning validation' })).toBeVisible();
      if (state === 'STALE') await expect(panel.getByText('Collection is stale.', { exact: false })).toBeVisible();
      if (state === 'QUALIFIED_SHADOW') await expect(panel.getByText('aaaaaaaaaaaa', { exact: true })).toBeVisible();
      if (state === 'QUARANTINED') await expect(panel.getByText('Shadow model quarantined:', { exact: false })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
      await page.screenshot({ path: `${process.env.AUTOTRADER_BROWSER_EVIDENCE}/v492-${state}-${width}.png`, fullPage: true });
    });
  }
}
