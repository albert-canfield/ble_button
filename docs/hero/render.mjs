#!/usr/bin/env node
// Renders docs/images/{hero.gif,hero.png,social-preview.png} from docs/hero/hero.html.
// Frames are captured deterministically: every Web Animation is paused and seeked per frame.
//
//   HERO_TOOLS=/path/with/node_modules/puppeteer-core  node docs/hero/render.mjs [gif|png|social|all]
//
// Env: CHROME (browser binary), FFMPEG (ffmpeg binary), HERO_WORK (frame dir, default: temp dir).
import { createRequire } from 'node:module';
import { mkdtempSync, mkdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const tools = resolve(process.env.HERO_TOOLS || here);
const puppeteer = createRequire(join(tools, 'noop.js'))('puppeteer-core');

const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const FFMPEG = process.env.FFMPEG || 'ffmpeg';
const OUT = resolve(here, '../images');
const HTML = pathToFileURL(join(here, 'hero.html')).href;
const FPS = 20;
const what = process.argv[2] || 'all';
const work = process.env.HERO_WORK ? resolve(process.env.HERO_WORK) : mkdtempSync(join(tmpdir(), 'ble-hero-'));
mkdirSync(work, { recursive: true });
mkdirSync(OUT, { recursive: true });

const ff = (...args) => execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', ...args], { stdio: 'inherit' });
const kb = (f) => `${(statSync(f).size / 1024).toFixed(0)} KB`;

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--hide-scrollbars', '--force-color-profile=srgb', '--font-render-hinting=none', '--allow-file-access-from-files'],
});

async function open(query, width, height) {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 2 });
  await page.goto(`${HTML}${query}`, { waitUntil: 'networkidle0' });
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(['400 14px Inter', '600 14px Inter', '800 14px Inter', '400 11px "JetBrains Mono"'].map((f) => document.fonts.load(f)));
    await Promise.all([...document.images].map((i) => i.decode().catch(() => {})));
  });
  return page;
}
const settle = (page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));

try {
  if (what === 'all' || what === 'gif' || what === 'png') {
    const page = await open('?mode=hero', 960, 480);
    if (what !== 'png') {
      const frames = join(work, 'frames');
      rmSync(frames, { recursive: true, force: true });
      mkdirSync(frames);
      const duration = await page.evaluate(() => window.__duration);
      const n = Math.round((duration / 1000) * FPS);
      for (let i = 0; i < n; i++) {
        await page.evaluate((t) => window.__seek(t), (i * 1000) / FPS);
        await settle(page);
        await page.screenshot({ path: join(frames, `f${String(i).padStart(4, '0')}.png`), clip: { x: 0, y: 0, width: 960, height: 480 } });
      }
      const palette = join(work, 'palette.png');
      const scale = 'scale=960:480:flags=lanczos';
      ff('-framerate', String(FPS), '-i', join(frames, 'f%04d.png'), '-vf', `${scale},palettegen=max_colors=256:stats_mode=full:reserve_transparent=0`, palette);
      ff('-framerate', String(FPS), '-i', join(frames, 'f%04d.png'), '-i', palette,
        '-lavfi', `${scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`,
        '-loop', '0', join(OUT, 'hero.gif'));
      console.log(`hero.gif  ${n} frames @ ${FPS} fps  ${kb(join(OUT, 'hero.gif'))}`);
    }
    await page.evaluate(() => window.__pose('hero'));
    await settle(page);
    const raw = join(work, 'hero-raw.png');
    await page.screenshot({ path: raw, clip: { x: 0, y: 0, width: 960, height: 480 } });
    ff('-i', raw, '-compression_level', '9', join(OUT, 'hero.png'));
    console.log(`hero.png  1920x960  ${kb(join(OUT, 'hero.png'))}`);
    await page.close();
  }
  if (what === 'all' || what === 'social') {
    const page = await open('?mode=social', 1280, 640);
    await page.evaluate(() => window.__pose('hero'));
    await settle(page);
    const raw = join(work, 'social-raw.png');
    await page.screenshot({ path: raw, clip: { x: 0, y: 0, width: 1280, height: 640 } });
    ff('-i', raw, '-vf', 'scale=1280:640:flags=lanczos', '-compression_level', '9', join(OUT, 'social-preview.png'));
    console.log(`social-preview.png  1280x640  ${kb(join(OUT, 'social-preview.png'))}`);
    await page.close();
  }
} finally {
  await browser.close();
  if (!process.env.HERO_WORK) rmSync(work, { recursive: true, force: true });
}
