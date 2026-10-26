import { expect, test } from '@playwright/test';
import { mockApi, signIn } from './fixtures/v43';

for(const width of [375,1440]) {
  test(`Dashboard keeps session on refresh and switches coin charts at ${width}px`, async({page})=>{
    const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
    await page.setViewportSize({width,height:1000});
    await mockApi(page);
    await signIn(page);
    await expect(page.getByRole('heading',{name:'Dashboard',level:1})).toBeVisible();
    await expect(page.getByText('Spent on buys',{exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'Your holdings',exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'What the trader is doing',exact:true})).toHaveCount(1);
    await expect(page.getByLabel('BTC-EUR chart').getByRole('img')).toBeVisible();
    await page.getByLabel('Coin market explorer').getByRole('button',{name:'View ETH-EUR chart',exact:true}).click();
    const chart=page.getByLabel('ETH-EUR chart');
    await expect(chart.getByRole('heading',{name:'ETH-EUR',exact:true})).toBeVisible();
    await expect(chart.getByRole('img')).toBeVisible();
    await chart.getByRole('button',{name:'24H',exact:true}).click();
    await chart.getByRole('button',{name:'Line',exact:true}).click();
    await expect(chart.getByRole('img')).toHaveAttribute('aria-label',/closing prices/);
    await page.reload();
    await expect(page.getByRole('heading',{name:'Dashboard',level:1})).toBeVisible();
    await expect(page.getByRole('button',{name:'Sign in',exact:true})).toHaveCount(0);
    expect(await page.evaluate(()=>Object.values({...localStorage,...sessionStorage}).join(' '))).not.toContain('fixture-password');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/synthetic-dashboard-${width}.png`,fullPage:true});
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
    await page.reload();
    await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test('Dashboard separates lifetime spending from remaining holdings and sale proceeds', async({page})=>{
  const { fixture } = await import('./fixtures/v43');
  const data:any=fixture();
  const timestamp=new Date().toISOString();
  data.personal_paper={observed_at:timestamp,runtime_matches:true,evidence_category:'SYNTHETIC_ACCEPTANCE',worker_health:{fresh:true},
    portfolio:{initial_cash:'7000',equity:'6999.95',available_cash:'6949.85',reserved_cash:'0',open_exposure:'50.10',total_net_pnl:'-.05',realized_pnl:'-.10',unrealized_pnl:'.05',risk_state:'HEALTHY',control:'RUNNING',current_drawdown:'0'},
    cash_flow:{spent_on_buys_eur:'100.10',sale_proceeds_eur:'49.95',fees_total_eur:'.15'},
    holdings:[{symbol:'ETH-EUR',quantity:'.5',cost_basis_eur:'50.05',market_value_eur:'50.10',unrealized_pnl_eur:'.05'}],
    markets:[{symbol:'ETH-EUR',last_observed_price:'100.2',fresh:true}],
    fills:[{symbol:'ETH-EUR',side:'BUY',quantity:'1',price:'100',fee:'.10',created_at:timestamp},{symbol:'ETH-EUR',side:'SELL',quantity:'.5',price:'100',fee:'.05',created_at:timestamp}],
    performance:{open_positions:1,closed_positions:0,capital_utilization:'.00715'},reconciliation:[],scan:{observed_at:timestamp,markets:['ETH-EUR']},position_monitor:{heartbeat:timestamp}};
  await mockApi(page,data);await signIn(page);
  await expect(page.locator('.dashboard-money').filter({hasText:'Spent on buys'})).toContainText('€100.10');
  await expect(page.locator('.dashboard-money').filter({hasText:'Invested now'})).toContainText('€50.10');
  await expect(page.locator('.dashboard-results')).toContainText('€49.95');
  await expect(page.getByRole('table',{name:'Dashboard filled trades'}).getByText('Bought',{exact:true})).toBeVisible();
  await expect(page.getByRole('table',{name:'Dashboard filled trades'}).getByText('Sold',{exact:true})).toBeVisible();
  await page.getByRole('table',{name:'Dashboard holdings'}).getByRole('button',{name:'ETH-EUR',exact:true}).click();
  await expect(page.getByLabel('ETH-EUR chart').getByRole('img')).toBeVisible();
});
