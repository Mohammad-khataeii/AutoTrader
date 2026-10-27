/* VPS-local browser acceptance. Secrets never leave the VPS or appear in output. */
const fs = require('fs');
const { chromium } = require('@playwright/test');
(async()=>{
  const base='/opt/personal-plan/staging';
  const values=Object.fromEntries(fs.readFileSync(base+'/config/.env.staging','utf8').split('\n').filter(l=>l.includes('=')&&!l.startsWith('#')).map(l=>{const p=l.indexOf('=');return [l.slice(0,p),l.slice(p+1)];}));
  const browser=await chromium.launch({executablePath:'/usr/bin/chromium-browser',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const results=[];
  for(const width of [375,1440]){
    const context=await browser.newContext({viewport:{width,height:1000}});
    const page=await context.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const mutations=[];page.on('request',r=>{if(r.method()!=='GET'&&!r.url().includes('/api/session'))mutations.push(r.url());});
    const url=process.env.DASHBOARD_URL||'http://127.0.0.1:13000';
    const parsed=new URL(url);
    const local=url==='http://127.0.0.1:13000';
    const privateRoute=parsed.protocol==='https:' && parsed.hostname===process.env.STAGING_TAILSCALE_HOST && parsed.hostname.endsWith('.ts.net');
    if(!local&&!privateRoute)throw new Error('staging_url_scope_mismatch');
    await page.goto(url);
    await page.getByLabel('Username',{exact:true}).fill(values.DASHBOARD_USERNAME||'admin');
    await page.getByLabel('Password',{exact:true}).fill(values.DASHBOARD_PASSWORD);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByRole('heading',{name:'Dashboard',exact:true}).waitFor();
    await page.locator('.header-actions').getByText('Running',{exact:true}).waitFor();
    await page.screenshot({path:`/output/aruba-dashboard-${width}.png`,fullPage:true});
    await page.getByRole('button',{name:'Opportunities',exact:true}).click();
    await page.getByRole('heading',{name:'Opportunity Radar',exact:true}).waitFor();
    await page.getByRole('table',{name:'RAOE opportunity radar'}).locator('tbody tr').first().waitFor();
    await page.screenshot({path:`/output/aruba-radar-${width}.png`,fullPage:true});
    await page.getByRole('button',{name:'Strategies',exact:true}).click();
    await page.getByRole('heading',{name:'Strategy Competition',exact:true}).waitFor();
    await page.getByRole('table',{name:'Prospective strategy competition'}).locator('tbody tr').nth(5).waitFor();
    await page.screenshot({path:`/output/aruba-competition-${width}.png`,fullPage:true});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if(overflow||errors.length||mutations.length)throw new Error('browser_integrity_failed');
    await page.reload();await page.getByRole('heading',{name:'Dashboard',exact:true}).waitFor();
    const cookies=await context.cookies();
    if(!cookies.some(c=>c.httpOnly&&c.sameSite==='Strict'))throw new Error('private_session_cookie_missing');
    await page.getByRole('button',{name:'Activity',exact:true}).click();
    await page.getByRole('heading',{name:'Persisted simulated orders',exact:true}).waitFor();
    await page.screenshot({path:`/output/aruba-activity-${width}.png`,fullPage:true});
    results.push({width,status:'PASS',javascript_errors:0,financial_mutations:0,session_survives_refresh:true});
    await context.close();
  }
  await browser.close();
  fs.writeFileSync('/output/browser-live.json',JSON.stringify({status:'PASS',results},null,2)+'\n');
  console.log(JSON.stringify({status:'PASS',results}));
})().catch(e=>{console.error(e.name+': browser acceptance failed');process.exit(1);});
