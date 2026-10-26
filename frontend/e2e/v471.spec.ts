import { expect, test } from '@playwright/test';
import { fixture, mockApi, signIn } from './fixtures/v43';

for(const width of [375,1440]) {
  test(`Position reports explain loss and primary health is independent at ${width}px`,async({page})=>{
    const data:any=fixture();
    await mockApi(page,data);
    await page.setViewportSize({width,height:1000});
    await page.route('**/api/personal-paper',route=>route.fulfill({json:{
      state:'PAPER_EXPERIMENTAL_ACTIVE',runtime_matches:true,worker_health:{fresh:true},reconciliation:[],
      portfolio:{initial_cash:'7000',equity:'6986.711990824714',available_cash:'6986.711990824714',reserved_cash:'0',open_exposure:'0',total_net_pnl:'-13.288009175286',risk_state:'HEALTHY',control:'RUNNING'},
      performance:{closed_positions:2,open_positions:0},cash_flow:{},scan:{rows:[]},
      trade_reports:[{position_id:'synthetic-ena-report',symbol:'ENA-EUR',strategy_id:'A3_COST_AWARE_CONTINUATION',net_pnl_eur:'-8.054783619034',gross_price_pnl_eur:'-6.667301688080',fees_eur:'1.387481930954',realized_r:'-.99',exit_reasons:['STOP'],explanation:'Price moved against the position and the protective stop executed. The price move lost money before fees.',entry_price:'.1881504',exit_price:'.1863508',initial_stop:'.1865',targets:['.1919','.1938','.1958'],planned_holding_seconds:10800,actual_holding_seconds:1976.46,entry_reason:{recovering:true},entry_regime:{trend:'MODERATE_BULLISH',benchmark:'ADVERSE'},exit_regime:null,entry_concerns_known_then:['BTC/ETH context was adverse at entry.'],issues:['Historical SELL label differs from entry plan; linked attribution corrected, raw record retained.'],fills:[]}]
    }}));
    const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
    await signIn(page);
    await expect(page.locator('.header-actions').getByText('Running',{exact:true})).toBeVisible();
    const panel=page.locator('.trade-reports');
    await panel.locator('.trade-report > summary').click();
    await expect(panel.getByText('Price P&L before fees',{exact:true})).toBeVisible();
    await expect(panel.getByText('The price move lost money before fees.',{exact:false})).toBeVisible();
    await expect(panel.getByText('Not recorded at exit',{exact:true})).toBeVisible();
    await expect(panel.getByText('BTC/ETH context was adverse at entry.',{exact:true})).toBeVisible();
    await expect(panel.getByText('Historical SELL label differs from entry plan; linked attribution corrected, raw record retained.',{exact:true})).toBeVisible();
    await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/v471-synthetic-report-${width}.png`,fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.getByRole('button',{name:'Activity',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Completed position reports'})).toBeVisible();
    expect(errors).toEqual([]);
  });
}
