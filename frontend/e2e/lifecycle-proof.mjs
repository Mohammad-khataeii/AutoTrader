// Optional local acceptance: real React build against the live test API/worker process.
import { chromium } from '@playwright/test';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
const backend = new URL(process.env.AUTOTRADER_LIFECYCLE_API);
if (backend.hostname !== '127.0.0.1') throw new Error('Local test API only');
const experiment = process.env.AUTOTRADER_LIFECYCLE_EXPERIMENT;
const assets = path.resolve('frontend/dist');
const server = http.createServer((req,res) => {
  if (req.url.startsWith('/api/') || req.url === '/readyz') {
    const proxy = http.request(new URL(req.url, backend), { method:req.method, headers:req.headers }, incoming => {
      res.writeHead(incoming.statusCode, incoming.headers); incoming.pipe(res);
    }); proxy.on('error', error => { res.writeHead(502); res.end(error.message); }); req.pipe(proxy); return;
  }
  const target = path.resolve(assets, '.'+new URL(req.url,'http://localhost').pathname);
  if (!target.startsWith(assets+path.sep) && target!==assets) {res.writeHead(403);res.end();return;}
  const file=fs.existsSync(target)&&fs.statSync(target).isFile()?target:path.join(assets,'index.html');
  const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'};
  res.writeHead(200,{'Content-Type':types[path.extname(file)]??'application/octet-stream'});fs.createReadStream(file).pipe(res);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port);
  await page.getByLabel('Username').fill('admin');await page.getByLabel('Password').fill('change-me');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('button',{name:'Shadow Trading Laboratory',exact:true}).click();
  await page.getByLabel('Experiment detail').selectOption(experiment);
  await page.getByText(/SYNTHETIC_ACCEPTANCE/).first().waitFor();
  const report=await page.request.get(new URL('/api/shadow/'+experiment,page.url()).href,{headers:{Authorization:'Basic '+Buffer.from('admin:change-me').toString('base64')}});
  if(!report.ok())throw new Error('Test API report unavailable');const body=await report.json();
  if(body.fills.length!==5||body.reconciliation.length||body.performance.closed_trades!==1)throw new Error('Expected real lifecycle did not complete');
  for(const fill of body.fills)await page.getByText(fill.fill_id,{exact:true}).waitFor();
  await page.getByText(/Official equity EUR 500.00/).waitFor();
  await page.screenshot({path:'docs/evidence/shadow-lifecycle-v4_2.png',fullPage:true});
  if(errors.length)throw new Error(errors.join('\n'));
  fs.writeFileSync('docs/evidence/v4_2-frontend-lifecycle.json',JSON.stringify({
    data_kind:body.manifest.data_kind,source_fingerprint:body.manifest.source_fingerprint,
    real_test_api:true,actual_react_build:true,persisted_fills_displayed:body.fills.length,
    closed_trades_displayed:body.performance.closed_trades,net_pnl:body.performance.net_pnl,
    fees:body.performance.fees,official_equity:500,reconciliation:body.reconciliation,page_errors:errors,
  },null,2)+'\n');
  console.log('React displayed actual persisted BUY/SELL lifecycle: 5 fills, 1 closed position, official EUR500, reconciliation=[]');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
