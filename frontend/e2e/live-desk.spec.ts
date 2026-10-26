import { expect, test } from '@playwright/test';
import { mockApi, signIn } from './fixtures/v43';

for (const width of [375, 1440]) {
  test(`live desk distinguishes waiting, rejection and real fill records at ${width}px`, async ({page}) => {
    await mockApi(page);
    let phase = 0;
    const stamp = new Date().toISOString();
    const errors: string[] = [], mutations: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (r.method() !== 'GET' && r.url().includes('/api/personal-paper')) mutations.push(r.method()); });
    await page.setViewportSize({width, height: 1000});
    await page.route('**/api/personal-paper', r => r.fulfill({json: {
      state: 'PAPER_EXPERIMENTAL_ACTIVE', observed_at: stamp, runtime_matches: true,
      evidence_category: 'SYNTHETIC_ACCEPTANCE', worker_health: {fresh: true},
      portfolio: {initial_cash: '7000', equity: '7000', available_cash: '7000', control: 'RUNNING', risk_state: 'HEALTHY'},
      performance: {buy_fills: 0, sell_fills: 0, closed_positions: 0}, reconciliation: [], strategies: [],
      scan: {observed_at: stamp, markets: ['BTC-EUR'], strategies_evaluated: 3}, position_monitor: {heartbeat: stamp},
    }}));
    await page.route('**/api/personal-paper/activity', r => {
      if (phase === 3) return r.fulfill({status: 503, json: {detail: 'unavailable'}});
      const decision = {id: `test-decision-${phase}`, kind: 'DECISION', timestamp: stamp, candle_at: stamp,
        symbol: 'BTC-EUR', strategy_id: 'A3_COST_AWARE_CONTINUATION', technical: phase > 0, economic: phase > 0,
        accepted: phase > 0, broker_status: phase === 1 ? 'REJECTED' : phase === 2 ? 'FILLED' : null,
        broker_reason: phase === 1 ? 'max_planned_loss_exceeded' : null,
        reasons: phase === 0 ? ['higher_15m_bullish', 'entry_not_chased'] : [], quote_amount: '700'};
      const events: object[] = [decision];
      if (phase === 1) events.unshift({id: 'rejected-order', kind: 'ORDER', timestamp: stamp, side: 'BUY', symbol: 'BTC-EUR', status: 'REJECTED', reason: 'max_planned_loss_exceeded', quantity: '.01', filled_quantity: '0'});
      if (phase === 2) {
        events.unshift({id: 'buy-fill', kind: 'FILL', timestamp: stamp, side: 'BUY', symbol: 'BTC-EUR', quantity: '.01', price: '70000', fee_eur: '.70'});
        events.unshift({id: 'sell-fill', kind: 'FILL', timestamp: stamp, side: 'SELL', symbol: 'BTC-EUR', quantity: '.003', price: '72000', fee_eur: '.216'});
      }
      return r.fulfill({json: {evaluations: [decision], events, evidence_category: 'SYNTHETIC_ACCEPTANCE', observed_at: stamp}});
    });
    await signIn(page);
    const desk = page.locator('.trader-live');
    await expect(desk.getByRole('heading', {name: 'What the trader is doing'})).toBeVisible();
    await expect(desk.getByText('The 15-minute trend has not turned bullish.', {exact: true}).first()).toBeVisible();
    await expect(desk.getByText('No order submitted', {exact: true})).toBeVisible();
    await desk.getByRole('button', {name: 'Orders & fills', exact: true}).click();
    await expect(desk.getByText(/No recorded orders or fills/)).toBeVisible();
    phase = 1;
    await expect(desk.getByRole('heading', {name: 'Not buying BTC-EUR · broker rejected'})).toBeVisible({timeout: 12000});
    await expect(desk.getByText('The planned loss is above the per-trade limit.', {exact: true}).first()).toBeVisible();
    await expect(desk.getByText(/Bought BTC-EUR/)).toHaveCount(0);
    phase = 2;
    await expect(desk.getByText('Bought BTC-EUR · paper fill', {exact: true})).toBeVisible({timeout: 12000});
    await expect(desk.getByText('Sold BTC-EUR · paper fill', {exact: true})).toBeVisible();
    await expect(desk.getByText('Deterministic test fixtures — this is not live market evidence.', {exact: true})).toBeVisible();
    await page.screenshot({path: `${process.env.AUTOTRADER_BROWSER_EVIDENCE}/synthetic-live-desk-${width}.png`, fullPage: true});
    phase = 3;
    await expect(desk.getByText('Waiting for fresh status', {exact: true})).toBeVisible({timeout: 12000});
    await expect(desk.getByText('Bought BTC-EUR · paper fill', {exact: true})).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
    expect(mutations).toEqual([]);
  });
}
