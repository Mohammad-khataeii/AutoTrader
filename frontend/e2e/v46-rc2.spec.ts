import { expect, test } from "@playwright/test";
import { mockApi, signIn } from "./fixtures/v43";

for (const width of [375, 1440]) {
  test(`RC2 separates current research, stale prices and failures at ${width}px`, async ({page}) => {
    const calls=await mockApi(page);
    await page.setViewportSize({width,height:1000});
    const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
    let state="CURRENT";
    const observation={symbol:"BTC-EUR",strategy_id:"A3_COST_AWARE_CONTINUATION",qualification_state:"RESEARCH_CANDIDATE",
      technical_eligible:true,economic_eligible:true,score:".8",as_of:"2026-10-22T12:00:00Z",
      explanation:"A completed recovery has acceptable modeled economics; predictive value remains unvalidated.",
      sizing:{quote_budget_eur:"52.50",scope:"RESEARCH_ASSUMPTION"},entry_plan:{stop:"98",targets:["104","106","108"]},
      regime_assessment:{trend:"MODERATE_BULLISH",structure:["COMPRESSION"]},
      economics:{measurements:{gross_target_return:".04",estimated_total_round_trip_cost_eur:".22",net_reward_risk:"1.5",conditional_target_net_eur:["1.9"],expected_net_stop_loss_eur:"1.2",breakeven_bid:"100.4",entry:{vwap:"100"}}},
      pipeline:[{stage:"EXPECTED_VALUE",reached:true,passed:null,reason:"UNCALIBRATED_RESEARCH_PAPER_ONLY"}]};
    await page.route('**/api/opportunities?**',r=>r.fulfill({json:{rows:[observation],status:state==='FAILED'?'ERROR':'OBSERVED',
      technical_candidates:state==='FAILED'?null:1,economically_viable_candidates:state==='FAILED'?null:1,stale:state!=='CURRENT',
      runtime_incident:state==='FAILED'?'ProviderOutage':null,
      research_freshness:{state,current:state==='CURRENT',age_seconds:170,next_evaluation_due_at:'2026-10-22T12:06:30Z'},
      market_freshness:{state:'STALE_QUOTES',execution_authorized:false},worker_health:{state:state==='FAILED'?'FAILED':state==='DELAYED'?'DELAYED':'HEALTHY',reason:'Current observation'},scanner_health:{state:'HEALTHY'},next_cursor:null}}));
    await signIn(page);await page.getByRole('button',{name:'Opportunities',exact:true}).click();
    await page.getByRole("tab", { name: "Baseline observations", exact: true }).click();
    await expect(page.getByRole('cell',{name:'Research candidate · unvalidated',exact:true})).toBeVisible();
    await expect(page.getByText('Stale quotes',{exact:true})).toBeVisible();
    await expect(page.getByText('Current completed-candle research.',{exact:false})).toBeVisible();
    await expect(page.getByText('Watch only · refresh needed',{exact:true})).toHaveCount(0);
    await page.getByRole('button',{name:'BTC-EUR A3 Cost-Aware Continuation',exact:true}).click();
    await expect(page.getByText('€52.50',{exact:true})).toBeVisible();
    await expect(page.getByText('€104.00 / €106.00 / €108.00',{exact:true})).toBeVisible();
    await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/rc2-opportunity-${width}.png`,fullPage:true});
    state='DELAYED';await page.getByRole('button',{name:'Refresh current view'}).click();
    await expect(page.getByText('Earlier research observation; current evaluation is unavailable.',{exact:false})).toBeVisible();
    state='FAILED';await page.getByRole('button',{name:'Refresh current view'}).click();
    await expect(page.getByRole('alert').filter({hasText:'ProviderOutage'})).toBeVisible();
    await expect(page.getByText('Unknown',{exact:true}).first()).toBeVisible();
    expect(calls.requests.filter(r=>r.method!=='GET')).toHaveLength(0);
    expect(errors).toEqual([]);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  });
}

test('RC2 loads full research evidence only on request', async ({page}) => {
  await mockApi(page);
  const requested:string[]=[];
  await page.route('**/api/strategies/comparison**',r=>{
    const url=new URL(r.request().url());requested.push(url.search);
    return r.fulfill({json:{successors:[],research:{schema:'comparison/4.6-rc2',baseline:{},successors:{},promotions:[]},research_detail:url.search?'FULL':'SUMMARY'}});
  });
  await signIn(page);
  await page.getByRole('button',{name:'Strategies',exact:true}).click();
  await page.getByRole('tab',{name:'Research comparison',exact:true}).click();
  await expect(page.getByRole('button',{name:'Load full research evidence',exact:true})).toBeVisible();
  expect(requested).toEqual(['']);
  await page.getByRole('button',{name:'Load full research evidence',exact:true}).click();
  await expect.poll(()=>requested).toEqual(['','?detail=true']);
  await expect(page.getByRole('button',{name:'Load full research evidence',exact:true})).toHaveCount(0);
});
