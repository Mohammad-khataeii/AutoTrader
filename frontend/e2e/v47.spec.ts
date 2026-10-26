import { expect, test } from "@playwright/test";
import { mockApi, signIn } from "./fixtures/v43";

for (const width of [375, 1440]) {
  test(`V4.7 separates shared capital, broker fills and research at ${width}px`, async ({page}) => {
    await mockApi(page);
    const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
    await page.setViewportSize({width,height:1000});
    await page.route('**/api/personal-paper',r=>r.fulfill({json:{
      state:'PAPER_EXPERIMENTAL_ACTIVE',evidence_category:'SYNTHETIC_ACCEPTANCE',runtime_matches:true,
      account_id:'PERSONAL_PLAN_PAPER_7000',portfolio:{initial_cash:'7000',equity:'7002',available_cash:'6300',reserved_cash:'0',open_exposure:'702',daily_equity_change:'2',total_net_pnl:'2',realized_pnl:'0',unrealized_pnl:'2',risk_state:'HEALTHY',control:'RUNNING',current_drawdown:'0'},
      performance:{buy_fills:1,sell_fills:0,open_positions:1,closed_positions:0,fees_eur:'.7',max_drawdown:'0'},
      reconciliation:[],scan:{observed_at:new Date().toISOString(),strategies_evaluated:3,markets:['BTC-EUR'],rows:[{symbol:'BTC-EUR',strategy_id:'A3_COST_AWARE_CONTINUATION',technical:true,economic:true,execution:'FILLED',reasons:[]}]},position_monitor:{heartbeat:new Date().toISOString()},
      strategies:[{strategy_id:'A3_COST_AWARE_CONTINUATION',strategy_version:'4.6.0-experimental.2',closed_positions:0,net_realized_pnl:'0',confidence:'INSUFFICIENT_INDEPENDENT_EVIDENCE'}],equity_history:[],
      positions:[{symbol:'BTC-EUR',strategy_id:'A3_COST_AWARE_CONTINUATION',quantity:'.01',average_entry_price:'70000',protective_stop:'68000',take_profit_targets:['74000','76000','78000']}],
      orders:[{order_id:'synthetic-1',symbol:'BTC-EUR',side:'BUY',status:'FILLED',quantity:'.01',average_fill_price:'70000',fee_eur:'.7',order_type:'MARKET',strategy_id:'A3_COST_AWARE_CONTINUATION',created_at:new Date().toISOString()}],research_review:{conclusion:'Insufficient independent prospective evidence',proposals:[]},
    }}));
    await signIn(page);
    await expect(page.getByRole('heading',{name:'Dashboard',exact:true})).toBeVisible();
    await expect(page.getByText('€7,002.00',{exact:true})).toBeVisible();
    await expect(page.getByText('Budget €7,000.00',{exact:false})).toBeVisible();
    await expect(page.getByText('Deterministic test fixtures',{exact:false})).toBeVisible();
    await page.getByRole('button',{name:'Activity',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Persisted simulated orders'})).toBeVisible();
    await expect(page.getByRole('table',{name:'Primary paper orders'}).getByText('BUY',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Opportunities',exact:true}).click();
    await expect(page.getByRole('table',{name:'Primary paper opportunity admission'}).getByText('FILLED',{exact:true})).toBeVisible();
    await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/v47-synthetic-opportunities-${width}.png`,fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}
