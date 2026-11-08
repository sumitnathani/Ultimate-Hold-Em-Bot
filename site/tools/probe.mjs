/**
 * DOM-measurement probe for the landing page.
 *
 *   node site/tools/probe.mjs [--url file:///...] [--widths 320,375,768,1440,2560]
 *
 * Screenshot/vision review is deliberately not used on this project -- it has
 * repeatedly hit a message-size limit and killed sessions. This reads the page
 * instead: getBoundingClientRect, scrollWidth vs clientWidth, computed styles,
 * console errors. Everything comes back as text.
 *
 * Zero dependencies. Drives headless Chrome over the DevTools protocol using
 * Node's built-in WebSocket (Node 22+).
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const CHROME = process.env.CHROME_PATH
  || 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf('--' + name);
  return i === -1 ? dflt : argv[i + 1];
};

const PAGE = resolve(arg('url', join(import.meta.dirname, '..', 'index.html')));
const WIDTHS = arg('widths', '320,375,768,1024,1440,2560').split(',').map(Number);
const PORT = Number(arg('port', '9333'));
const SETTLE_MS = Number(arg('settle', '2500'));
const SCROLL = argv.includes('--scroll');

// --------------------------------------------------------------------------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function httpJson(path) {
  const res = await fetch(`http://127.0.0.1:${PORT}${path}`);
  return res.json();
}

/** Minimal CDP client: send(method, params) -> result, plus event capture. */
function connect(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  const listeners = new Map();

  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id !== undefined) {
      const p = pending.get(msg.id);
      if (p) {
        pending.delete(msg.id);
        msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
      }
    } else {
      (listeners.get(msg.method) || []).forEach((fn) => fn(msg.params));
    }
  });

  const ready = new Promise((res, rej) => {
    ws.addEventListener('open', res);
    ws.addEventListener('error', rej);
  });

  return {
    ready,
    on(method, fn) {
      if (!listeners.has(method)) listeners.set(method, []);
      listeners.get(method).push(fn);
    },
    send(method, params = {}) {
      const mid = ++id;
      return new Promise((resolve, reject) => {
        pending.set(mid, { resolve, reject });
        ws.send(JSON.stringify({ id: mid, method, params }));
      });
    },
    close: () => ws.close(),
  };
}

// --------------------------------------------------------------------------

/** Runs in the page. Returns a plain object; must be self-contained. */
const MEASURE = `(() => {
  const de = document.documentElement;
  const out = {
    viewport: { w: innerWidth, h: innerHeight },
    doc: { scrollW: de.scrollWidth, clientW: de.clientWidth, scrollH: de.scrollHeight },
    horizontalOverflow: de.scrollWidth > de.clientWidth + 1,
    flat: de.classList.contains('flat'),
    fontsReady: document.fonts ? document.fonts.status : 'n/a',
  };

  const label = (el) => {
    let s = el.tagName.toLowerCase();
    if (typeof el.className === 'string' && el.className.trim()) {
      s += '.' + el.className.trim().split(/\\s+/).slice(0, 3).join('.');
    }
    return s;
  };

  out.sections = [...document.querySelectorAll('section, footer')].map((s) => {
    const r = s.getBoundingClientRect();
    return {
      id: s.id || label(s),
      top: Math.round(r.top + scrollY),
      h: Math.round(r.height),
      w: Math.round(r.width),
    };
  });

  // Anything sticking out past the viewport. Decorative layers that are clipped
  // by an overflow:hidden ancestor (.swarm inside the pinned stage, the fixed
  // grain/glow) are not layout bugs, so they are skipped.
  const SKIP = '.swarm, .swarm *, .grain, .glow';
  const offenders = [];
  document.querySelectorAll('body *').forEach((el) => {
    if (el.matches(SKIP)) return;
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed' || cs.visibility === 'hidden' || cs.display === 'none') return;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    if (r.right > innerWidth + 1 || r.left < -1) {
      offenders.push({
        sel: label(el),
        left: Math.round(r.left),
        right: Math.round(r.right),
        w: Math.round(r.width),
      });
    }
  });
  out.offenders = offenders.slice(0, 20);
  out.offenderCount = offenders.length;

  out.ledgerCounts = [...document.querySelectorAll('.ledger__count')]
    .map((e) => e.textContent.trim());
  out.readout = [...document.querySelectorAll('[data-val]')]
    .map((e) => e.dataset.val + '=' + e.textContent.trim());

  // Sample of the text the page actually renders, for copy checks.
  out.trapStats = [...document.querySelectorAll('.trap__stat')]
    .map((d) => d.querySelector('dt').textContent.trim() + ': ' + d.querySelector('dd').textContent.trim());

  // States of everything the scroll drives. Read after a full scroll pass to
  // prove the motion actually fired and landed on the right values.
  const op = (sel) => {
    const el = document.querySelector(sel);
    return el ? Number(getComputedStyle(el).opacity).toFixed(2) : null;
  };
  out.animated = {
    ledgerRule: op('.ledger__rule'),
    ledgerCount: op('.ledger__count'),
    ledgerNote: op('.ledger__note'),
    measureLine: op('.measure__line'),
    measureVal: op('.measure__val'),
    trap: op('.trap'),
    boardCard: op('.board .card'),
    caption1: op('.captions .caption:nth-child(1)'),
    caption5: op('.captions .caption:nth-child(5)'),
  };
  out.measureLineTransform = (() => {
    const el = document.querySelector('.measure__line');
    return el ? getComputedStyle(el).transform : null;
  })();

  return out;
})()`;

// --------------------------------------------------------------------------

const userDataDir = mkdtempSync(join(tmpdir(), 'probe-chrome-'));
let chrome;

try {
  chrome = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--remote-allow-origins=*',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--hide-scrollbars',
    `--user-data-dir=${userDataDir}`,
    'about:blank',
  ], { stdio: 'ignore' });

  // Wait for the debugging endpoint.
  let targets = null;
  for (let i = 0; i < 60; i++) {
    try {
      targets = await httpJson('/json/list');
      if (targets.some((t) => t.type === 'page')) break;
    } catch { /* not up yet */ }
    await sleep(250);
  }
  if (!targets) throw new Error('Chrome did not expose a debugging endpoint');

  const page = targets.find((t) => t.type === 'page');
  const cdp = connect(page.webSocketDebuggerUrl);
  await cdp.ready;

  const errors = [];
  cdp.on('Runtime.exceptionThrown', (p) => {
    errors.push('EXCEPTION: ' + (p.exceptionDetails?.exception?.description
      || p.exceptionDetails?.text || 'unknown'));
  });
  cdp.on('Runtime.consoleAPICalled', (p) => {
    if (p.type === 'error' || p.type === 'warning') {
      errors.push(p.type.toUpperCase() + ': '
        + p.args.map((a) => a.value ?? a.description ?? '').join(' '));
    }
  });
  cdp.on('Log.entryAdded', (p) => {
    if (p.entry.level === 'error') errors.push('LOG: ' + p.entry.text);
  });

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable');

  // --reduced forces the fallback path: the page must collapse to a complete,
  // readable, stacked document with nothing hidden.
  if (argv.includes('--reduced')) {
    await cdp.send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
    });
  }

  const url = pathToFileURL(PAGE).href;
  const loaded = new Promise((res) => cdp.on('Page.loadEventFired', res));

  const results = [];
  for (const width of WIDTHS) {
    // mobile:false on purpose -- we want the CSS laid out at exactly `width`,
    // not Chrome's mobile viewport heuristic on top of it.
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width, height: Math.max(640, Math.round(width * 0.62)),
      deviceScaleFactor: 1, mobile: false,
    });
    await cdp.send('Page.navigate', { url });
    await loaded.catch(() => {});
    await sleep(SETTLE_MS);

    // A --scroll pass walks the whole document so every ScrollTrigger fires,
    // then re-measures. It is how "the motion landed on the right values" gets
    // checked without looking at the page.
    if (SCROLL) {
      const steps = 40;
      await cdp.send('Runtime.evaluate', {
        expression: `(() => {
          const h = document.documentElement.scrollHeight - innerHeight;
          return new Promise((done) => {
            let i = 0;
            const tick = () => {
              window.scrollTo(0, (h * i) / ${steps});
              if (++i > ${steps}) return done(true);
              setTimeout(tick, 90);
            };
            tick();
          });
        })()`,
        returnByValue: true, awaitPromise: true,
      });
      await sleep(3000);
    }

    const { result } = await cdp.send('Runtime.evaluate', {
      expression: MEASURE, returnByValue: true, awaitPromise: true,
    });
    results.push({ width, ...result.value });
  }

  console.log(JSON.stringify({ page: PAGE, errors, results }, null, 2));
  cdp.close();
} finally {
  if (chrome) chrome.kill();
  await sleep(300);
  try { rmSync(userDataDir, { recursive: true, force: true }); } catch { /* best effort */ }
}
