import { expect, test } from '@playwright/test';
import fs from 'node:fs';

// Explicit opt-in: the persistent server is reviewed read-only. Financial controls
// and synthetic lifecycle tests belong to the separate disposable harness.
test.skip(process.env.AUTOTRADER_MAC_SERVER !== '1', 'Local server review requires explicit opt-in');

for (const width of [375, 1440]) {
  test(`Mac server read-only navigation at ${width}px`, async ({page}) => {
    const values=Object.fromEntries(fs.readFileSync(process.env.AUTOTRADER_MAC_ENV ?? '../.env.local','utf8')
      .split(/\r?\n/).filter(l=>l.includes('=')).map(l=>[l.slice(0,l.indexOf('=')),l.slice(l.indexOf('=')+1)]));
    const errors:string[]=[],mutations:string[]=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.url().includes('/api/') && r.method()!=='GET') mutations.push(`${r.method()} ${new URL(r.url()).pathname}`);});
    await page.setViewportSize({width,height:1000});
    await page.goto(process.env.AUTOTRADER_MAC_SERVER_URL ?? 'http://localhost:3000');
    await page.getByLabel('Username',{exact:true}).fill(values.DASHBOARD_USERNAME);
    await page.getByLabel('Password',{exact:true}).fill(values.DASHBOARD_PASSWORD);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    for (const area of ['Overview','Opportunities','Strategies','Activity','Research','Decision Insights','Settings']) {
      if(area==='Settings') await page.locator('.advanced-menu > summary').click();
      await page.getByRole('button',{name:area,exact:true}).click();
      await expect(page.getByRole('heading',{name:area,level:1,exact:true})).toBeVisible();
      await expect(page.getByText('Loading this workspace…',{exact:true})).toHaveCount(0);
      if(area==='Overview') {
        await expect(page.getByRole('heading',{name:'€7,000 virtual portfolio',exact:true})).toBeVisible();
        await expect(page.getByText('Starting virtual balance €7,000.00',{exact:true})).toBeVisible();
        const balances=page.getByLabel('Official simulated balance and results');
        await expect(page.getByText('Worker connected',{exact:true})).toBeVisible();
        await expect(page.getByLabel('Personal Plan shared paper portfolio').getByText(/Financial reconciliation passed/)).toBeVisible();
        await expect(balances.getByText('Unavailable',{exact:true})).toHaveCount(0);
        await expect(balances.locator('strong').first()).toHaveText('€500.00');
      }
      if(area==='Opportunities') {
        await expect(page.getByRole('table',{name:'Opportunity qualification'})).toBeVisible();
        await page.getByRole('button',{name:'More markets',exact:true}).click();
        await expect(page.getByRole('button',{name:'Latest observations',exact:true})).toBeEnabled();
        await page.getByRole('button',{name:'Latest observations',exact:true}).click();
        const constrained=page.getByRole('row').filter({has:page.getByRole('cell',{name:'Cost constrained',exact:true})});
        if(await constrained.count()) {
          await constrained.first().getByRole('button').click();
          await expect(page.getByText('Indicative entry',{exact:false})).toBeVisible();
          await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/mac-live-cost-constrained-${width}.png`,fullPage:true});
        }
      }
      if(area==='Strategies') {
        await page.getByRole('tab',{name:'Research comparison',exact:true}).click();
        await expect(page.getByRole('table',{name:'Strategy research comparison'})).toBeVisible();
      }
      expect(await page.locator('body').innerText()).not.toMatch(/\bAutoTrader\b/i);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/mac-live-${area.toLowerCase().replaceAll(' ','-')}-${width}.png`,fullPage:true});
    }
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
    await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
    expect(mutations).toEqual([]);
    expect(errors).toEqual([]);
    const loading=await page.evaluate(()=>{
      const navigation=performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming;
      const resources=performance.getEntriesByType('resource') as PerformanceResourceTiming[];
      return {dom_content_loaded_ms:navigation.domContentLoadedEventEnd,load_ms:navigation.loadEventEnd,
        resource_count:resources.length,js_transfer_bytes:resources.filter(r=>r.name.endsWith('.js')).reduce((sum,r)=>sum+r.transferSize,0)};
    });
    fs.writeFileSync(`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/mac-browser-loading-${width}.json`,JSON.stringify({
      kind:'ACTUAL_PERSISTENT_LOCAL_SERVER',viewport_width:width,read_only:true,api_mutations:mutations,
      page_errors:errors,...loading},null,2)+'\n');
  });
}
