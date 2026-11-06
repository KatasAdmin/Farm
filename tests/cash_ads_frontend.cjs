// Exercises the cash-ad screen with local SDK doubles only.
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const assert = require('node:assert/strict');

const page = fs.readFileSync('cash-ads-preview.html', 'utf8');
const monetag = fs.readFileSync('assets/cash-ads-sdk.js', 'utf8');
const adsgram = fs.readFileSync('assets/adsgram-fallback.js', 'utf8');

async function scenario({sdkError, status = 'valued', allowFallback = true, adsgramDone = true}) {
  const dom = new JSDOM(page, {url:'https://farm.test', runScripts:'outside-only'});
  const w = dom.window;
  const calls = [];
  let fallbacks = 0;
  let closed = 0;
  try {
    w.Telegram = {WebApp:{initData:'isolated', close:() => closed++}};
    w.setTimeout = fn => { fn(); };
    w.fetch = async (url, request) => {
      const endpoint = url.split('/').at(-1);
      calls.push(endpoint);
      assert.equal(JSON.parse(request.body).telegram_data, 'isolated');
      const replies = {
        status:{enabled:true, adsgram_enabled:allowFallback, adsgram_block_id:'58218'},
        prepare:{ymid:'cash_test', zone_id:12193261, request_var:'cash_rewarded_interstitial'},
        'attempt-result':{status}
      };
      return {ok:true, json:async () => replies[endpoint] || {ok:true}};
    };
    w.show_12193261 = async options => {
      assert.equal(options.type, 'end');
      assert.equal(options.ymid, 'cash_test');
      if (sdkError) throw new Error(sdkError);
      // A client claim of payment has no effect on the flow.
      return {reward_event_type:'valued'};
    };
    w.Adsgram = {init:({blockId, debug}) => {
      assert.equal(blockId, '58218');
      assert.equal(debug, false);
      return {show:async () => {
        fallbacks++;
        return {done:adsgramDone, error:false};
      }};
    }};
    w.eval(monetag);
    w.eval(adsgram);
    await w.eval(w.document.querySelector('script:not([src])').textContent);
    return {calls, fallbacks, closed, retry:!w.document.getElementById('watch').disabled};
  } finally {
    w.close();
  }
}

(async () => {
  const noFill = await scenario({sdkError:'Empty feed'});
  assert.equal(noFill.fallbacks, 1);
  assert.ok(noFill.calls.includes('abandon'));
  assert.ok(!noFill.calls.includes('finish'));
  assert.equal(noFill.closed, 1);
  const unpaid = await scenario({status:'non_valued'});
  assert.equal(unpaid.fallbacks, 1);
  assert.ok(unpaid.calls.includes('finish'));
  assert.equal((await scenario({status:'valued'})).fallbacks, 0);
  const pending = await scenario({status:'pending'});
  assert.equal(pending.fallbacks, 0);
  assert.equal(pending.calls.filter(call => call === 'attempt-result').length, 7);
  const skipped = await scenario({sdkError:'Rejected'});
  assert.equal(skipped.fallbacks, 0);
  assert.equal(skipped.retry, true);
  assert.equal((await scenario({sdkError:'Empty feed', allowFallback:false})).fallbacks, 0);
  const failedBackup = await scenario({status:'non_valued', adsgramDone:false});
  assert.equal(failedBackup.closed, 0);
  assert.equal(failedBackup.retry, true);
  console.log('7 cash ad screen scenarios passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
