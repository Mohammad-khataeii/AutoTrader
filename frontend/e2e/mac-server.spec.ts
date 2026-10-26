import { expect, test } from '@playwright/test';
import fs from 'node:fs';

// Explicit opt-in: the financial server is reviewed read-only. Browser session
// creation/deletion verify authentication without changing financial records. Controls
// and synthetic lifecycle tests belong to the separate disposable harness.
test.skip(process.env.AUTOTRADER_MAC_SERVER !== '1', 'Local server review requires explicit opt-in');

for (const width of [375, 1440]) {
  test(`Mac server read-only navigation at ${width}px`, async ({page}) => {
    test.setTimeout(60000);
    const values=Object.fromEntries(fs.readFileSync(process.env.AUTOTRADER_MAC_ENV ?? '../.env.local','utf8')
      .split(/\r?\n/).filter(l=>l.includes('=')).map(l=>[l.slice(0,l.indexOf('=')),l.slice(l.indexOf('=')+1)]));
    const errors:string[]=[],mutations:string[]=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.url().includes('/api/') && r.method()!=='GET' && !r.url().endsWith('/api/session')) mutations.push(`${r.method()} ${new URL(r.url()).pathname}`);});
    await page.setViewportSize({width,height:1000});
    await page.goto(process.env.AUTOTRADER_MAC_SERVER_URL ?? 'http://localhost:3000');
    await page.getByLabel('Username',{exact:true}).fill(values.DASHBOARD_USERNAME);
    await page.getByLabel('Password',{exact:true}).fill(values.DASHBOARD_PASSWORD);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    for (const area of ['Dashboard','Opportunities','Strategies','Activity','Research','Decision Insights','Settings']) {
      if(area==='Settings') await page.locator('.advanced-menu > summary').click();
      await page.getByRole('button',{name:area,exact:true}).click();
      await expect(page.getByRole('heading',{name:area,level:1,exact:true})).toBeVisible();
      await expect(page.getByText('Loading this workspace…',{exact:true})).toHaveCount(0);
      if(area==='Dashboard') {
        await expect(page.getByText('Budget €7,000.00',{exact:false})).toBeVisible();
        await expect(page.getByRole('heading',{name:'Your holdings',exact:true})).toBeVisible();
        const desk=page.locator('.trader-live');
        await expect(desk.getByRole('heading',{name:'What the trader is doing'})).toBeVisible();
        await expect(desk.getByText('Worker connected',{exact:true})).toBeVisible();
        await expect(desk.locator('.trader-event').first()).toBeVisible();
        const options=desk.locator('select option');
        if(await options.count()>1) {
          await desk.getByLabel('Inspect another recent candidate').selectOption({index:1});
          await expect(desk.getByText(/Pinned evaluation/)).toBeVisible();
          await desk.getByRole('button',{name:'Follow latest',exact:true}).click();
        }
        await page.waitForResponse(r=>r.url().endsWith('/api/personal-paper/activity') && r.status()===200,{timeout:12000});
        await desk.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/actual-live-desk-${width}.png`});
        await expect(page.getByLabel('BTC-EUR chart').getByRole('img')).toBeVisible();
        await page.getByLabel('Coin market explorer').getByRole('button',{name:'View ETH-EUR chart',exact:true}).click();
        await expect(page.getByLabel('ETH-EUR chart').getByRole('heading',{name:'ETH-EUR',exact:true})).toBeVisible();
        await page.reload();
        await expect(page.getByRole('heading',{name:'Dashboard',level:1,exact:true})).toBeVisible();
        await expect(page.getByText('Budget €7,000.00',{exact:false})).toBeVisible();
        await expect(page.getByLabel('BTC-EUR chart').getByRole('img')).toBeVisible();
        await expect(page.getByRole('button',{name:'Sign in',exact:true})).toHaveCount(0);
        const sessionCookie=(await page.context().cookies()).find(c=>c.name==='personal_plan_session');
        expect(sessionCookie?.httpOnly).toBe(true);
        expect(sessionCookie?.sameSite).toBe('Strict');
        expect(await page.evaluate(()=>document.cookie)).not.toContain('personal_plan_session');
      }
      if(area==='Opportunities') {
        await expect(page.getByRole('table',{name:'Opportunity qualification'})).toBeVisible();
        const more=page.getByRole('button',{name:'More markets',exact:true});
        if(await more.isEnabled()) {
          await more.click();
          await expect(page.getByRole('button',{name:'Latest observations',exact:true})).toBeEnabled();
          await page.getByRole('button',{name:'Latest observations',exact:true}).click();
        } else {
          await expect(page.getByRole('button',{name:'Latest observations',exact:true})).toBeDisabled();
        }
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
    await page.reload();
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
      page_errors:errors,refresh_preserved_session:true,logout_survived_refresh:true,http_only_cookie:true,...loading},null,2)+'\n');
  });
}
