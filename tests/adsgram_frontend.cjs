// Mock SDK only. All AdsGram requests are simulated.
const { JSDOM } = require('jsdom');
const { readFileSync } = require('node:fs');
const assert = require('node:assert/strict');
const source = readFileSync('assets/monetag-rewards.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function scenario(result) {
  const { window: w } = new JSDOM(
    '<style id="rewarded-ads-ui-paused"></style><div><p id="warning"></p></div><section id="wallet"></section>',
    { runScripts: 'outside-only', url: 'https://farm.test' }
  );
  w.setInterval = () => 0;
  const calls = [], notifications = [], handlers = new Map();
  w.Adsgram = {
    init(options) {
      assert.equal(options.blockId, '123');
      assert.equal(options.debug, true);
      assert.equal(options.debugBannerType, 'RewardedVideo');
      return {
        addEventListener(name, callback) { handlers.set(name, callback); },
        removeEventListener(name) { handlers.delete(name); },
        show() {
          assert.equal(calls.at(-1).path, '/api/ads/adsgram/start');
          if (result === 'completed') return Promise.resolve({ done: true, error: false });
          if (result === 'no_fill') handlers.get('onBannerNotFound')();
          return Promise.reject(new Error('SDK failure'));
        }
      };
    }
  };
  w.api = async (path, payload, headers) => {
    calls.push({ path, payload });
    assert.equal(headers['X-Telegram-Init-Data'], 'test-telegram-signature');
    if (path === '/api/ads/adsgram/start') return { ymid: 'test-id' };
    if (path === '/api/ads/adsgram/finish') return { ok: true, rewarded: false };
    return {
      provider: 'adsgram', visible: true, enabled: true, test_mode: true, block_id: '123',
      remaining_today: 50, remaining_hour: 10, retry_after: 0, history: [],
      rewards: { grain: { progress: 0 }, coins: { progress: 0 } }
    };
  };
  w.toast = message => notifications.push(message);
  w.el = id => w.document.getElementById(id);
  w.refresh = () => assert.fail('SDK events must not trigger economy updates');
  w.eval(`var token='test',pending=false,state={farm:{effective_grain_shortage:1}},
    selectedResource='grain',purchase={},adProgress={},adRewards={grain:[1,1],coins:[1,2]};
    function tgInitData(){return 'test-telegram-signature';}`);
  w.eval(source);
  await tick();
  const button = w.document.getElementById('free-grain-shortage');
  assert.equal(button.disabled, false);
  assert.match(button.textContent, /Тест AdsGram/);
  button.click();
  button.click();
  await tick();
  await tick();
  assert.equal(calls.filter(call => call.path.endsWith('/start')).length, 1);
  assert.equal(calls.filter(call => call.path.endsWith('/finish')).length, 1);
  assert.equal(calls.find(call => call.path.endsWith('/finish')).payload.result, result);
  assert.equal(handlers.size, 0);
  assert.equal(w.eval('adProgress.grain'), 0);
  assert.equal(notifications.length, 1);
  w.close();
}

async function run() {
  for (const result of ['completed', 'no_fill', 'sdk_error']) await scenario(result);
  console.log('3 mock AdsGram SDK scenarios passed.');
}
module.exports = run;
if (require.main === module) run().catch(error => { console.error(error); process.exitCode = 1; });
