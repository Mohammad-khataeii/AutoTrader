import { expect, test } from '@playwright/test';
import { mockApi, signIn } from './fixtures/v43';

for (const width of [320, 375, 390, 1440]) {
  test(`Strategy workspace tabs stay reachable without page overflow at ${width}px`, async ({page}) => {
    await mockApi(page);
    await page.setViewportSize({width,height:1000});
    const strategies=['B2_CONFIRMED_COMPRESSION','C2_LIQUIDITY_RETEST',
      'A3_COST_AWARE_CONTINUATION','B3_STATEFUL_BREAKOUT','E3_ADAPTIVE_RELATIVE_STRENGTH',
      'RAOE_EARLY_RECOVERY','RAOE_TREND_PULLBACK','RAOE_BREAKOUT_RETEST'];
    await page.route('**/api/intelligence/competition',route=>route.fulfill({json:{
      experiments:strategies.map((strategy_id,i)=>({experiment_id:`synthetic-${i}`,strategy_id,
        version:i<2?'4.2.0-experimental.1':'4.8.0-raoe.1',evidence_category:'SYNTHETIC_ACCEPTANCE',
        portfolio:{realized_pnl:'0',unrealized_pnl:'0'},performance:{closed_trades:0,fees:'0',max_drawdown:'0'}}))
    }}));
    await signIn(page);
    await page.getByRole('button',{name:'Strategies',exact:true}).click();
    await expect(page.getByRole('table',{name:'Prospective strategy competition'}).locator('tbody tr')).toHaveCount(8);
    const tabs=page.getByRole('tablist',{name:'Strategy workspace'});
    for (const name of ['Strategy Competition','Accounts','Research comparison']) {
      const tab=tabs.getByRole('tab',{name,exact:true});
      await expect(tab).toBeVisible();
      const bounds=await tab.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(width);
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/strategy-tabs-${width}.png`,fullPage:true});
  });
}

for (const width of [375, 1440]) {
  test(`RAOE radar, uncertainty and prospective review at ${width}px`, async ({page}) => {
    await mockApi(page);
    await page.setViewportSize({width,height:1000});
    const errors: string[]=[];page.on('pageerror',e=>errors.push(e.message));
    let stale=false;
    const row={symbol:'TEST-EUR',strategy_id:'RAOE_EARLY_RECOVERY',technical:true,economic:false,
      status:'WATCHING',raoe_regime:{labels:['EMERGING_BULLISH_RECOVERY'],benchmark:'MIXED',timeframes:{'60':{trend:'BEARISH'}}},
      entry_plan:{entry:'100',stop:'98',targets:['104','105','106'],alternatives:[{method:'PATIENT_IOC',entry:'99.8',executable_now:false}]},
      reasons:['target_cost_headroom'],pipeline:[{stage:'STRATEGY_SETUP',state:'PASSED'},{stage:'ECONOMIC_QUALIFICATION',state:'FAILED'},
        {stage:'PORTFOLIO_RISK',state:'NOT_REACHED'}]};
    await page.route('**/api/intelligence*',route=>route.fulfill({json:{
      status:stale?'STALE_OR_UNAVAILABLE':'CURRENT',rows:[{...row,status:stale?'STALE':'WATCHING'}],
      observed_at:new Date().toISOString(),discovery:{supported_eur:61},
      unscanned_or_excluded:[{symbol:'USDC-EUR',status:'REJECTED',reason:'PEGGED_ASSET_DIRECTIONAL_EXCLUSION',price:'0.9',spread_bps:'2',quote_volume_24h:'2000000'}],
      missed:[{event_id:'synthetic-fixture',symbol:'TEST-EUR',strategy_id:row.strategy_id,observed_at:new Date().toISOString(),
        rejection:'target_cost_headroom',outcome:{classification:'POTENTIAL_FAVORABLE_MOVE_NOT_PROVEN_EXECUTABLE'}}]
    }}));
    await signIn(page);
    await page.getByRole('button',{name:'Opportunities',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Opportunity Radar',exact:true})).toBeVisible();
    await expect(page.getByRole('table',{name:'RAOE opportunity radar'}).getByText('Watching',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'TEST-EUR Raoe early recovery',exact:false}).click();
    await expect(page.getByText('Not Reached',{exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'Missed Opportunities',exact:true})).toBeVisible();
    await expect(page.getByText('Potential Favorable Move Not Proven Executable',{exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/raoe-radar-${width}.png`,fullPage:true});
    stale=true;
    await page.waitForTimeout(15500);
    await expect(page.getByRole('table',{name:'RAOE opportunity radar'}).getByText('Stale',{exact:true})).toBeVisible();
    expect(errors).toEqual([]);
  });
}
