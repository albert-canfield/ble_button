# Hero assets
- `hero.html` is the self-contained scene: open it in Chrome to preview the 6 s loop (`?mode=social` = 1280×640 card, `?pose=hero` = still).
- `render.mjs` pauses and seeks every Web Animation frame by frame in headless Chrome, then writes `docs/images/hero.gif`, `hero.png` and `social-preview.png` with ffmpeg.
- Regenerate: `npm i --prefix /tmp/hero-tools puppeteer-core && HERO_TOOLS=/tmp/hero-tools node docs/hero/render.mjs [gif|png|social|all]`
- Override binaries with `CHROME=…` / `FFMPEG=…`; set `HERO_WORK=/some/dir` to keep the raw 2× frames.
