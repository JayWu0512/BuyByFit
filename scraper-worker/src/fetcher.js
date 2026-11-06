// Polite fetch with browser-like headers, retries on 429/5xx, and block detection.

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
const BLOCK_MARKERS = /(Access Denied|px-captcha|captcha-delivery|Request unsuccessful|Pardon Our Interruption|are you a robot)/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function fetchPage(url, { retries = 2, cacheTtl = 3600 } = {}) {
  let last;
  for (let attempt = 0; attempt <= retries; attempt++) {
    let res;
    try {
      res = await fetch(url, {
      headers: {
        "User-Agent": UA,
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
      redirect: "follow",
      cf: { cacheTtl, cacheEverything: true },
      });
    } catch (err) {
      last = { status: 0, html: "", blocked: false, fetchError: String(err?.message || err), finalUrl: url };
      await sleep(800 * (attempt + 1));
      continue;
    }
    const html = await res.text();
    const blocked = res.status === 403 || (res.status === 200 && html.length < 20000 && BLOCK_MARKERS.test(html));
    last = { status: res.status, html, blocked, finalUrl: res.url || url };
    if (res.status === 429 || res.status >= 500) {
      await sleep(800 * (attempt + 1));
      continue;
    }
    return last;
  }
  return last;
}
