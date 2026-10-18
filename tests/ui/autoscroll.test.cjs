const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {webkit} = require('playwright');

const backend = path.resolve(__dirname, '../../src/backend');
let browser;
before(async () => { browser = await webkit.launch(); });
after(async () => { await browser?.close(); });

// Serve the real UI and local assets; only the model stream is controlled by the test.
async function chat(t) {
  let streamReady;
  const stream = new Promise(resolve => { streamReady = resolve; });
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost').pathname;
    if (url === '/api/chat') {
      res.writeHead(200, {'Content-Type': 'application/x-ndjson'});
      res.flushHeaders();
      streamReady(event => res.write(JSON.stringify(event) + '\n'));
      return;
    }
    if (url === '/api/health' || url === '/api/config') {
      res.writeHead(200, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({model_ok: true, model: 'test-model', default_steps: 16, default_max_tokens: 4096}));
      return;
    }
    const file = url === '/' ? path.join(backend, 'page.html') :
      url.startsWith('/static/') && !url.includes('..') ? path.join(backend, url) : null;
    if (!file || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
    res.setHeader('Content-Type', file.endsWith('.html') ? 'text/html' : file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : 'application/octet-stream');
    res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const page = await browser.newPage({viewport: {width: 1000, height: 650}, reducedMotion: 'reduce'});
  t.after(async () => {
    await page.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => document.querySelector('#ovStartup').classList.contains('hidden'));
  await page.evaluate(() => {
    history = [{role: 'user', content: 'Conversazione precedente'},
      {role: 'assistant', content: 'Paragrafo precedente.\n\n'.repeat(35)}];
    renderHistory();
  });
  await frames(page);
  await page.locator('#ta').fill('Continua la spiegazione.\n'.repeat(8));
  await page.locator('#btnSend').click();
  const emit = await stream;
  await frames(page);
  return {page, emit};
}

async function frames(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function position(page) {
  return page.locator('#scroll').evaluate(s => ({top: s.scrollTop, gap: s.scrollHeight - s.clientHeight - s.scrollTop}));
}
async function draft(page, emit, text) {
  // Real streaming paints are throttled by at most 280ms on long responses.
  await new Promise(resolve => setTimeout(resolve, 300));
  emit({diff: {step: 8, total_steps: 16, block: 0, draft: text}});
  await page.waitForFunction(text => document.querySelector('.stream-txt')?.textContent.includes(text.slice(-20)), text);
  await frames(page);
}

test('follows the bottom after inserting the denoise controls and a multiline prompt', async t => {
  const {page} = await chat(t);
  assert((await position(page)).gap <= 4, 'the new denoise block must remain visible');
});

test('follows drafts that grow, shrink and grow again', async t => {
  const {page, emit} = await chat(t);
  await draft(page, emit, 'Primo blocco lungo. '.repeat(150) + 'FINE UNO');
  assert((await position(page)).gap <= 4, 'the growing draft must stay in view');
  await draft(page, emit, 'Bozza breve FINE DUE');
  await draft(page, emit, 'Nuova bozza ancora più lunga. '.repeat(200) + 'FINE TRE');
  assert((await position(page)).gap <= 4, 'reflow must not be mistaken for manual scrolling');
});

test('lets the user scroll up and resumes following when they return to the bottom', async t => {
  const {page, emit} = await chat(t);
  await draft(page, emit, 'Risposta in formazione. '.repeat(150) + 'FINE QUATTRO');
  await page.locator('#scroll').hover({position: {x: 500, y: 120}});
  await page.mouse.wheel(0, -400);
  await page.waitForFunction(() => {
    const s = document.querySelector('#scroll'); return s.scrollHeight - s.clientHeight - s.scrollTop > 200;
  });
  const before = await position(page);
  await draft(page, emit, 'Altra risposta molto lunga. '.repeat(200) + 'FINE CINQUE');
  assert(Math.abs((await position(page)).top - before.top) < 4, 'new tokens must not pull the reader down');
  await page.locator('#scroll').evaluate(s => { s.scrollTop = s.scrollHeight; });
  await frames(page);
  await draft(page, emit, 'Prosegue la risposta. '.repeat(300) + 'FINE SEI');
  assert((await position(page)).gap <= 4, 'returning to the bottom must enable following again');
});

test('keeps following layout changes between denoise events', async t => {
  const {page, emit} = await chat(t);
  await draft(page, emit, 'Risposta lunga con testo. '.repeat(150) + 'FINE SETTE');
  await page.setViewportSize({width: 800, height: 450});
  await frames(page);
  assert((await position(page)).gap <= 4, 'resizing must not leave the response below the viewport');
});
