const { test, expect } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8765/';

async function openFirstShort(page) {
  await page.locator('.card-open[data-short-id]').first().waitFor();
  await page.locator('.card-open[data-short-id]').first().click();
  await page.locator('.short-player iframe').waitFor({ state: 'attached', timeout: 15000 });
}

test.describe('post-review hardening regressions', () => {
  for (const viewport of [{ width: 360, height: 720 }, { width: 390, height: 740 }]) {
    test(`${viewport.width}x${viewport.height} Short actions are reachable and Tab dismisses the menu`, async ({ browser }) => {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto(`${BASE}?qa=short-${viewport.width}x${viewport.height}`, { waitUntil: 'domcontentloaded' });
      await openFirstShort(page);

      const stack = page.locator('.short-action-stack');
      await expect(stack.locator(':scope > button, :scope > a')).toHaveCount(8);
      const bounds = await stack.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return { top: rect.top, bottom: rect.bottom, viewport: innerHeight };
      });
      expect(bounds.top).toBeGreaterThanOrEqual(0);
      expect(bounds.bottom).toBeLessThanOrEqual(viewport.height);
      await stack.evaluate((element) => { element.scrollTop = element.scrollHeight; });
      expect(await stack.locator(':scope > button, :scope > a').last().evaluate((element) => {
        const item = element.getBoundingClientRect();
        const parent = element.parentElement.getBoundingClientRect();
        return item.top >= parent.top - 1 && item.bottom <= parent.bottom + 1;
      })).toBe(true);

      expect(await page.locator('.short-player iframe').evaluate((iframe) => {
        const rect = iframe.getBoundingClientRect();
        return [0.2, 0.5, 0.8].map((ratio) => document.elementFromPoint(
          rect.left + rect.width * 0.5,
          rect.top + rect.height * ratio,
        ) === iframe);
      })).toEqual([true, true, true]);

      const activeId = await page.locator('.short-shell').getAttribute('data-video-context-id');
      const more = page.locator('#shortVideoActionsButton');
      await more.click();
      await expect(page.locator('.video-action-menu')).toBeVisible();
      await page.keyboard.press('Tab');
      await expect(page.locator('#videoActionMenuRoot')).toBeHidden();
      await expect(more).toBeFocused();
      expect(await page.locator('.short-shell').getAttribute('data-video-context-id')).toBe(activeId);
      expect(errors).toEqual([]);
      await context.close();
    });
  }

  test('malicious feed destinations are replaced by canonical YouTube URLs and popup is isolated', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 740 } });
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE.slice(0, -1) });
    const page = await context.newPage();
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'share', { configurable: true, value: undefined });
    });
    let maliciousId = '';
    await page.route('**/data/videos.json?*', async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      const item = data.items.find((candidate) => candidate.type === 'short');
      maliciousId = item.id;
      item.url = 'javascript:alert(document.domain)';
      item.channelUrl = 'data:text/html,<script>alert(1)</script>';
      item.channelId = 'javascript:alert(1)';
      item.handle = 'javascript:alert(1)';
      await route.fulfill({ response, json: data });
    });
    await page.goto(`${BASE}?qa=malicious-destinations`, { waitUntil: 'domcontentloaded' });
    await openFirstShort(page);
    expect(await page.locator('.short-shell').getAttribute('data-video-context-id')).toBe(maliciousId);

    const canonical = `https://www.youtube.com/watch?v=${maliciousId}`;
    expect(await page.locator('.short-action-stack > a').getAttribute('href')).toBe('https://www.youtube.com/');
    await page.locator('#shortDescriptionButton').click();
    expect(await page.locator('.short-description > a').getAttribute('href')).toBe(canonical);
    await page.locator('#shortDrawerClose').click();
    await page.locator('#shortShareButton').click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(canonical);

    await page.evaluate(() => {
      window.__qaPopup = null;
      window.open = (url) => {
        window.__qaPopup = { url: String(url), opener: { unsafe: true }, focus() {} };
        return window.__qaPopup;
      };
    });
    await page.locator('#shortFloatButton').click();
    await expect.poll(() => page.evaluate(() => Boolean(window.__qaPopup))).toBe(true);
    const popupState = await page.evaluate(() => ({ url: window.__qaPopup.url, opener: window.__qaPopup.opener }));
    expect(new URL(popupState.url).searchParams.has('url')).toBe(false);
    expect(popupState.opener).toBe(null);
    await context.close();
  });

  test('ordinary Up Next click preserves hidden prior video for ten-second Previous replay', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`${BASE}?qa=queue-backtrack`, { waitUntil: 'domcontentloaded' });
    await page.locator('.card-open[data-video-id]').first().click();
    await page.locator('.player-frame iframe').waitFor({ state: 'attached', timeout: 15000 });
    const firstId = await page.locator('.player-main').getAttribute('data-video-context-id');
    const nextLink = page.locator('[data-up-next-list] .queue-card').first();
    const secondId = await nextLink.getAttribute('data-video-id');
    await nextLink.click();
    await expect(page.locator('.player-main')).toHaveAttribute('data-video-context-id', secondId);
    await expect(page.locator('[data-player-nav="-1"]')).toBeEnabled();
    await page.locator('[data-player-nav="-1"]').click();
    await expect(page.locator('.player-main')).toHaveAttribute('data-video-context-id', firstId);
    expect(errors).toEqual([]);
    await context.close();
  });

  test('mobile feed cards and Up Next expose visible More triggers', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 740 } });
    const page = await context.newPage();
    await page.goto(`${BASE}?qa=mobile-card-more`, { waitUntil: 'domcontentloaded' });
    const card = page.locator('.video-card').first();
    await expect(card.locator('[data-open-video-menu-id]')).toBeVisible();
    await card.locator('[data-open-video-menu-id]').click();
    await expect(page.locator('.video-action-menu')).toBeVisible();
    await expect(page.locator('[data-video-action]')).toHaveCount(11);
    await page.locator('[data-close-video-menu]').click();
    await card.locator('.card-open').click();
    const queueItem = page.locator('[data-up-next-list] .queue-item').first();
    await expect(queueItem.locator('[data-open-video-menu-id]')).toBeVisible();
    await context.close();
  });

  test('real card and Up Next links preserve native context menus while More stays custom', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    await page.goto(`${BASE}?qa=native-link-menu`, { waitUntil: 'domcontentloaded' });
    const card = page.locator('.video-card').first();
    const cardLink = card.locator('.card-open');
    expect(await cardLink.evaluate((link) => link.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, button: 2,
    })))).toBe(true);
    await expect(page.locator('.video-action-menu')).toHaveCount(0);
    await cardLink.focus();
    expect(await cardLink.evaluate((link) => link.dispatchEvent(new KeyboardEvent('keydown', {
      bubbles: true, cancelable: true, key: 'ContextMenu',
    })))).toBe(true);
    await expect(page.locator('.video-action-menu')).toHaveCount(0);
    await card.locator('[data-open-video-menu-id]').click();
    await expect(page.locator('.video-action-menu')).toBeVisible();
    await page.locator('[data-close-video-menu]').click();

    await cardLink.click();
    const queueItem = page.locator('[data-up-next-list] .queue-item').first();
    const queueLink = queueItem.locator('.queue-card');
    expect(await queueLink.evaluate((link) => link.dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, button: 2,
    })))).toBe(true);
    await expect(page.locator('.video-action-menu')).toHaveCount(0);
    await queueItem.locator('[data-open-video-menu-id]').click();
    await expect(page.locator('.video-action-menu')).toBeVisible();
    await context.close();
  });

  test('Gemini popup loses opener before any cross-origin navigation', async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      permissions: ['clipboard-read', 'clipboard-write'],
    });
    const page = await context.newPage();
    await page.goto(`${BASE}?qa=popup-order`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      window.alert = () => {};
      window.__externalPopup = null;
      window.open = (initialUrl) => {
        const record = { initialUrl: String(initialUrl), opener: { unsafe: true }, navigatedTo: '', openerAtNavigation: 'unset' };
        record.location = {
          replace(url) {
            record.navigatedTo = String(url);
            record.openerAtNavigation = record.opener;
          },
        };
        record.close = () => {};
        window.__externalPopup = record;
        return record;
      };
    });
    await page.locator('.card-open[data-video-id]').first().click();
    await page.locator('[data-gemini-id]').first().click();
    await expect.poll(() => page.evaluate(() => Boolean(window.__externalPopup?.navigatedTo))).toBe(true);
    const state = await page.evaluate(() => ({
      initialUrl: window.__externalPopup.initialUrl,
      navigatedTo: window.__externalPopup.navigatedTo,
      openerAtNavigation: window.__externalPopup.openerAtNavigation,
    }));
    expect(state.initialUrl).toBe('about:blank');
    expect(state.navigatedTo).toMatch(/^https:\/\/gemini\.google\.com\/app/);
    expect(state.openerAtNavigation).toBe(null);
    await context.close();
  });

  test('ignoring the active player stops progress before watched can override ignored', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => {
      if (window.top !== window) return;
      localStorage.clear();
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          const target = {
            seekTo() {}, playVideo() {}, pauseVideo() {}, destroy() {},
            getDuration() { return 120; },
            getCurrentTime() { return 40; },
            getPlayerState() { return 1; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    const page = await context.newPage();
    await page.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    await page.goto(`${BASE}?qa=ignore-active`, { waitUntil: 'domcontentloaded' });
    await page.locator('.card-open[data-video-id]').first().click();
    const ignoredId = await page.locator('.player-main').getAttribute('data-video-context-id');
    await page.locator('.player-main [data-open-video-menu-id]').click();
    await page.locator('[data-video-action="toggle-ignored"]').click();
    await expect(page.locator('.player-main')).not.toHaveAttribute('data-video-context-id', ignoredId);
    await page.waitForTimeout(1800);
    const localState = await page.evaluate((id) => ({
      ignored: Boolean(JSON.parse(localStorage.getItem('nexafeed-ignored-v1') || '{}')[id]),
      watched: Boolean(JSON.parse(localStorage.getItem('nexafeed-watched-v1') || '{}')[id]),
    }), ignoredId);
    expect(localState).toEqual({ ignored: true, watched: false });
    await context.close();
  });

  test('removing watched from the active player cannot be reversed by stale progress', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => {
      if (window.top !== window) return;
      localStorage.clear();
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          const target = {
            seekTo() {}, playVideo() {}, pauseVideo() {}, destroy() {},
            getDuration() { return 120; },
            getCurrentTime() { return 40; },
            getPlayerState() { return 1; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    const page = await context.newPage();
    await page.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    await page.goto(`${BASE}?qa=remove-active-watched`, { waitUntil: 'domcontentloaded' });
    await page.locator('.card-open[data-video-id]').first().click();
    const watchedId = await page.locator('.player-main').getAttribute('data-video-context-id');
    await expect.poll(() => page.evaluate((id) => Boolean(JSON.parse(localStorage.getItem('nexafeed-watched-v1') || '{}')[id]), watchedId)).toBe(true);
    await page.locator('.player-main [data-open-video-menu-id]').click();
    await expect(page.locator('[data-video-action="toggle-watched"]')).toContainText('Remove from Watch History');
    await page.locator('[data-video-action="toggle-watched"]').click();
    await expect(page.locator('.player-main')).not.toHaveAttribute('data-video-context-id', watchedId);
    await page.waitForTimeout(1800);
    expect(await page.evaluate((id) => Boolean(JSON.parse(localStorage.getItem('nexafeed-watched-v1') || '{}')[id]), watchedId)).toBe(false);
    await context.close();
  });

  test('float popup initializes the YouTube player only once', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 760, height: 470 } });
    await context.addInitScript(() => {
      if (!location.pathname.endsWith('/float.html')) return;
      localStorage.clear();
      window.__floatPlayerCount = 0;
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          window.__floatPlayerCount += 1;
          const target = {
            playVideo() {}, loadVideoById() {}, destroy() {},
            getDuration() { return 120; },
            getCurrentTime() { return 0; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    const page = await context.newPage();
    await page.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    await page.goto(`${BASE}float.html?id=Gx2QN7FvKAM&type=long&title=Float+init`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      window.onYouTubeIframeAPIReady();
      window.onYouTubeIframeAPIReady();
    });
    await expect.poll(() => page.evaluate(() => window.__floatPlayerCount)).toBe(1);
    await context.close();
  });

  test('float popup periodically saves progress and finalizes on Close', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 760, height: 470 } });
    await context.addInitScript(() => {
      if (!location.pathname.endsWith('/float.html')) return;
      localStorage.clear();
      window.__floatCloseRequested = false;
      window.close = () => { window.__floatCloseRequested = true; };
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          const target = {
            playVideo() {}, loadVideoById() {}, destroy() {},
            getDuration() { return 120; },
            getCurrentTime() { return 40; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    const page = await context.newPage();
    await page.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    const videoId = 'Gx2QN7FvKAM';
    await page.goto(`${BASE}float.html?id=${videoId}&type=long&title=Float+progress`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => window.onYouTubeIframeAPIReady());
    await expect.poll(() => page.evaluate((id) => JSON.parse(localStorage.getItem('nexafeed-progress-v1') || '{}')[id]?.seconds, videoId)).toBe(40);
    await page.locator('#closeButton').click();
    expect(await page.evaluate(() => window.__floatCloseRequested)).toBe(true);
    expect(await page.evaluate((id) => Boolean(JSON.parse(localStorage.getItem('nexafeed-watched-v1') || '{}')[id]), videoId)).toBe(true);
    await context.close();
  });

  test('external Ignore stops a float popup without re-marking it watched', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 760, height: 470 } });
    await context.addInitScript(() => {
      if (!location.pathname.endsWith('/float.html')) return;
      window.__floatCloseRequested = false;
      window.__floatDestroyed = 0;
      window.close = () => { window.__floatCloseRequested = true; };
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          const target = {
            playVideo() {}, pauseVideo() {}, loadVideoById() {},
            destroy() { window.__floatDestroyed += 1; },
            getDuration() { return 120; },
            getCurrentTime() { return 40; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    const controller = await context.newPage();
    await controller.goto(`${BASE}?qa=float-controller`, { waitUntil: 'domcontentloaded' });
    await controller.evaluate(() => localStorage.clear());
    const popup = await context.newPage();
    await popup.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    const videoId = 'Gx2QN7FvKAM';
    await popup.goto(`${BASE}float.html?id=${videoId}&type=long&title=Float+ignore`, { waitUntil: 'domcontentloaded' });
    await popup.evaluate(() => window.onYouTubeIframeAPIReady());
    await controller.evaluate((id) => {
      localStorage.setItem('nexafeed-ignored-v1', JSON.stringify({ [id]: Date.now() }));
    }, videoId);
    await expect.poll(() => popup.evaluate(() => window.__floatCloseRequested)).toBe(true);
    expect(await popup.evaluate(() => window.__floatDestroyed)).toBe(1);
    await popup.waitForTimeout(1800);
    expect(await controller.evaluate((id) => Boolean(JSON.parse(localStorage.getItem('nexafeed-watched-v1') || '{}')[id]), videoId)).toBe(false);
    await context.close();
  });

  test('explicit Ignore destroys a matching in-page Float before stale progress', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => {
      if (window.top !== window) return;
      localStorage.clear();
      window.open = () => null;
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          const target = {
            playVideo() {}, pauseVideo() {}, destroy() {},
            getDuration() { return 120; },
            getCurrentTime() { return 40; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    const page = await context.newPage();
    await page.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    await page.goto(`${BASE}?qa=inline-float-ignore`, { waitUntil: 'domcontentloaded' });
    const card = page.locator('.video-card').first();
    const videoId = await card.locator('[data-open-video-menu-id]').getAttribute('data-open-video-menu-id');
    await card.locator('[data-open-video-menu-id]').click();
    await page.locator('[data-video-action="float"]').click();
    await expect(page.locator('#inlineFloatingPlayer')).toBeVisible();
    await card.locator('[data-open-video-menu-id]').evaluate((button) => button.click());
    await page.locator('[data-video-action="toggle-ignored"]').click();
    await expect(page.locator('#inlineFloatingPlayer')).toHaveCount(0);
    await page.waitForTimeout(1800);
    expect(await page.evaluate((id) => Boolean(JSON.parse(localStorage.getItem('nexafeed-ignored-v1') || '{}')[id]), videoId)).toBe(true);
    expect(await page.evaluate((id) => Boolean(JSON.parse(localStorage.getItem('nexafeed-watched-v1') || '{}')[id]), videoId)).toBe(false);
    await context.close();
  });

  test('closing an in-page Float persists progress and applies skip thresholds', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => {
      if (window.top !== window) return;
      localStorage.clear();
      window.open = () => null;
      window.__inlineFloatConstructed = false;
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          window.__inlineFloatConstructed = true;
          const target = {
            playVideo() {}, pauseVideo() {}, destroy() {},
            getDuration() { return 120; },
            getCurrentTime() { return 10; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    const page = await context.newPage();
    await page.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    await page.goto(`${BASE}?qa=inline-float-close`, { waitUntil: 'domcontentloaded' });
    const card = page.locator('.video-card').first();
    const videoId = await card.locator('[data-open-video-menu-id]').getAttribute('data-open-video-menu-id');
    await card.locator('[data-open-video-menu-id]').click();
    await page.locator('[data-video-action="float"]').click();
    await expect(page.locator('#inlineFloatingPlayer')).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__inlineFloatConstructed)).toBe(true);
    await page.locator('#inlineFloatingPlayer [data-close-float]').click();
    await expect(page.locator('#inlineFloatingPlayer')).toHaveCount(0);
    expect(await page.evaluate((id) => JSON.parse(localStorage.getItem('nexafeed-progress-v1') || '{}')[id]?.seconds, videoId)).toBe(10);
    expect(await page.evaluate((id) => Boolean(JSON.parse(localStorage.getItem('nexafeed-ignored-v1') || '{}')[id]), videoId)).toBe(true);
    expect(await page.evaluate((id) => Boolean(JSON.parse(localStorage.getItem('nexafeed-watched-v1') || '{}')[id]), videoId)).toBe(false);
    await context.close();
  });

  test('a newer in-page Float supersedes delayed initialization for the old video', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => {
      if (window.top !== window) return;
      localStorage.clear();
      window.open = () => null;
    });
    const page = await context.newPage();
    await page.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    await page.goto(`${BASE}?qa=float-generation`, { waitUntil: 'domcontentloaded' });
    const cards = page.locator('.video-card');
    const firstId = await cards.nth(0).locator('[data-open-video-menu-id]').getAttribute('data-open-video-menu-id');
    const secondId = await cards.nth(1).locator('[data-open-video-menu-id]').getAttribute('data-open-video-menu-id');
    await cards.nth(0).locator('[data-open-video-menu-id]').click();
    await page.locator('[data-video-action="float"]').click();
    await expect(page.locator('#inlineFloatingPlayer')).toBeVisible();
    await cards.nth(1).locator('[data-open-video-menu-id]').evaluate((button) => button.click());
    await expect(page.locator('[data-video-action="float"]')).toBeVisible();
    await page.locator('[data-video-action="float"]').click();
    await page.evaluate(() => {
      window.__floatingConstructed = [];
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          window.__floatingConstructed.push(options.videoId);
          const target = {
            playVideo() {}, destroy() {},
            getDuration() { return 120; },
            getCurrentTime() { return 0; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    await expect.poll(() => page.evaluate(() => window.__floatingConstructed)).toEqual([secondId]);
    expect(firstId).not.toBe(secondId);
    await context.close();
  });

  test('Long Previous control refreshes when ten-second transient history expires', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => {
      if (window.top !== window) return;
      localStorage.clear();
      window.YT = {
        PlayerState: { ENDED: 0, PLAYING: 1 },
        Player: function (_id, options) {
          const target = {
            seekTo() {}, playVideo() {}, pauseVideo() {}, destroy() {},
            getDuration() { return 120; },
            getCurrentTime() { return 0; },
            getPlayerState() { return 1; },
          };
          setTimeout(() => options.events.onReady({ target }), 0);
          return target;
        },
      };
    });
    const page = await context.newPage();
    await page.route('https://www.youtube.com/iframe_api', (route) => route.abort());
    await page.goto(`${BASE}?qa=long-expiry`, { waitUntil: 'domcontentloaded' });
    await page.locator('.card-open[data-video-id]').first().click();
    await page.locator('[data-up-next-list] .queue-card').first().click();
    await expect(page.locator('[data-player-nav="-1"]')).toBeEnabled();
    await page.waitForTimeout(10400);
    await expect(page.locator('[data-player-nav="-1"]')).toBeDisabled();
    await context.close();
  });
});
