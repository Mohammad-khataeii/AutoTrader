import { expect, test } from '@playwright/test';
import { mockApi, signIn } from './fixtures/v43';

for (const width of [320, 375, 390, 1440]) {
  test(`V4.9 precise PEPE plan, execution uncertainty and episode review at ${width}px`, async ({page}) => {
    await mockApi(page);
    await page.setViewportSize({width,height:1000});
    const errors: string[]=[];page.on('pageerror',error=>errors.push(error.message));
    const row={symbol:'PEPE-EUR',strategy_id:'RAOE_TREND_PULLBACK',technical:true,economic:false,status:'REJECTED',
      market_price:'0.0000040776',completed_return_30m:'.021',relative_return_30m:'.02',spread_bps:'6.8',quote_volume_24h:'2000000',
      reasons:['first_target_destroyed_by_execution_costs'],
      raoe_regime:{labels:['ESTABLISHED_BULLISH_TREND'],benchmark:'MIXED',timeframes:{'240':{trend:'UNKNOWN',contiguous_bars:15,required_bars:21}}},
      entry_plan:{entry:'0.0000040776',stop:'0.0000040454',targets:['0.0000040798','0.0000040804','0.0000040809'],next_overhead:'0.0000041044',
        structure:{classification:'MEANINGFUL_UNBROKEN_RESISTANCE',zones:[{price:'0.000004081',classification:'MINOR_PRICE_NOISE'}]}},
      economics:{measurements:{breakeven_bid:'0.0000040928',expected_net_stop_loss_eur:'8.10',estimated_total_round_trip_cost_eur:'3.08'}},
      pipeline:[{stage:'STRATEGY_SETUP',state:'PASSED'},{stage:'ECONOMIC_QUALIFICATION',state:'FAILED'},{stage:'PORTFOLIO_RISK',state:'NOT_REACHED'}]};
    await page.route('**/api/intelligence*',route=>route.fulfill({json:{status:'CURRENT',observed_at:new Date().toISOString(),rows:[row],discovery:{supported_eur:61},
      benchmark_sync:{'BTC-EUR':{alignment_status:'UNKNOWN',unknown_reason:'MISSING_REQUESTED_CLOSED_BAR'}},
      runtime_diagnostics:{market_metrics:{payload:{http_429:2}}},
      missed:[{symbol:'PEPE-EUR',strategy_id:row.strategy_id,observed_at:new Date().toISOString(),rejection:'first_target_destroyed_by_execution_costs',outcome:{classification:'INCONCLUSIVE'}}],
      episodes:[{episode_id:'fixture-only',symbol:'PEPE-EUR',first_observed_at:new Date().toISOString(),signal_count:42,position_conflicts:0}],
      episode_scope:{hours:48,signals:42,possibly_truncated:false}}}));
    await signIn(page);
    await page.getByRole('button',{name:'Opportunities',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Opportunity Radar',exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'Runtime diagnostics',exact:true})).toBeVisible();
    await page.getByRole('table',{name:'RAOE opportunity radar'}).getByRole('button').click();
    await expect(page.getByRole('heading',{name:'PEPE-EUR · Trade Plan Inspector',exact:true})).toBeVisible();
    const plan=page.getByLabel('Causal trade plan');
    await expect(plan.getByText('€0.0000040776',{exact:true})).toBeVisible();
    await expect(plan.getByText('€0.0000040454',{exact:true})).toBeVisible();
    await expect(page.getByText('First target is below modeled executable break-even. This plan does not cover costs.',{exact:true})).toBeVisible();
    await expect(page.getByRole('table',{name:'Overlapping market episodes'}).getByText('42',{exact:true})).toBeVisible();
    await expect(page.getByText('Execution unproven; no independent win implied',{exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/v49-pepe-plan-${width}.png`,fullPage:true});
  });
}

test('V4.9 competition preserves archived evidence and explicit holding identities',async ({page})=>{
  await mockApi(page);
  await page.route('**/api/intelligence/competition',route=>route.fulfill({json:{experiments:[{
    experiment_id:'synthetic-continuation',strategy_id:'RAOE_BREAKOUT_CONTINUATION',version:'4.9.0-raoe.1',evidence_category:'SYNTHETIC_ACCEPTANCE',
    exit_policy:{version:'4.9.0-continuation-exit.1',holding_seconds:14400},forward_evidence_seconds:7200,orders:0,fills:0,
    portfolio:{equity:'500',realized_pnl:'0',unrealized_pnl:'0'},performance:{closed_trades:0,fees:'0',max_drawdown:'0'}
  },{experiment_id:'retained-fixture',strategy_id:'RAOE_EARLY_RECOVERY',version:'4.8.0-raoe.1',archived_at:'2026-10-28T00:00:00Z',
    evidence_category:'SYNTHETIC_ACCEPTANCE',portfolio:{equity:'500'},performance:{closed_trades:0}}]}}));
  await signIn(page);
  await page.getByRole('button',{name:'Strategies',exact:true}).click();
  const table=page.getByRole('table',{name:'Prospective strategy competition'});
  await expect(table.locator('tbody tr')).toHaveCount(2);
  await expect(table.getByText('4.9.0-continuation-exit.1',{exact:false})).toBeVisible();
  await expect(table.getByText('Legacy unbound',{exact:false})).toBeVisible();
});
