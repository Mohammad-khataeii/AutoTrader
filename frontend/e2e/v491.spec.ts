import { expect, test } from '@playwright/test';
import { mockApi, signIn } from './fixtures/v43';

for (const width of [375, 1440]) {
  test(`V4.9.1 primary context explains a blocked recovery at ${width}px`, async ({page}) => {
    await mockApi(page);
    await page.setViewportSize({width,height:1000});
    const errors: string[]=[];page.on('pageerror',error=>errors.push(error.message));
    const row={id:'context-block',kind:'DECISION',timestamp:new Date().toISOString(),candle_at:new Date().toISOString(),
      symbol:'ADA-EUR',strategy_id:'RAOE_EARLY_RECOVERY',technical:true,economic:true,accepted:false,
      entry_eligible:false,reasons:['primary_recovery_reclaim'],
      primary_admission:{version:'4.9.1-primary-admission.1',base_entry_eligible:true,
        gates:{primary_context_ready:true,primary_current_candle:true,primary_macro_context:true,
          primary_local_reclaim:true,primary_recovery_reclaim:false}},
      pipeline:[{stage:'STRATEGY_SETUP',state:'PASSED'},{stage:'ECONOMIC_QUALIFICATION',state:'PASSED'},
        {stage:'PRIMARY_CONTEXT',state:'FAILED'}]};
    await page.route('**/api/personal-paper/activity',route=>route.fulfill({json:{evaluations:[row],events:[row],evidence_category:'SYNTHETIC_ACCEPTANCE'}}));
    await signIn(page);
    const desk=page.locator('.trader-live');
    await expect(desk.getByText('Primary context',{exact:true})).toBeVisible();
    await expect(desk.getByText('The recovery has not reclaimed the completed fifteen-minute trend mean with a rising close.',{exact:true}).first()).toBeVisible();
    await expect(desk.getByText('No order submitted',{exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({path:`${process.env.AUTOTRADER_BROWSER_EVIDENCE}/v491-context-${width}.png`,fullPage:true});
  });
}
