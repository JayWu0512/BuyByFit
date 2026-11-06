// Amazon Berkeley Objects (ABO) — CC BY 4.0, credit "Amazon.com".
// Streams one listings shard (listings_0..f.json.gz), filters furniture, stops early at `limit`.

const BASE = "https://amazon-berkeley-objects.s3.amazonaws.com";
export const ABO_DEFAULT_TYPES = ["SOFA", "CHAIR", "TABLE", "BED", "BED_FRAME", "DESK", "OTTOMAN", "BENCH",
  "STOOL_SEATING", "SHELF", "BOOKCASE", "CABINET", "DRESSER", "NIGHTSTAND", "HOME_FURNITURE_AND_DECOR",
  "RUG", "LAMP", "MIRROR", "TV_STAND", "COFFEE_TABLE", "END_TABLE", "HEADBOARD"];
const UNIT_TO_CM = { inches: 2.54, inch: 2.54, centimeters: 1, cm: 1, millimeters: 0.1, feet: 30.48, meters: 100 };
const LICENSE = "CC BY 4.0, credit Amazon.com (Amazon Berkeley Objects)";

async function* gzLines(url) {
  const res = await fetch(url, { cf: { cacheTtl: 86400, cacheEverything: true } });
  if (!res.ok) throw new Error(`ABO fetch ${res.status} for ${url}`);
  const reader = res.body.pipeThrough(new DecompressionStream("gzip")).pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += value;
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        if (line) yield line;
      }
    }
    if (buf) yield buf;
  } finally {
    reader.cancel().catch(() => {});
  }
}

const en = (arr) => {
  if (!Array.isArray(arr)) return null;
  const pref = ["en_US", "en_GB", "en_CA", "en_AU", "en_IN"];
  for (const t of pref) { const h = arr.find((e) => e.language_tag === t && e.value); if (h) return h.value; }
  return arr.find((e) => String(e.language_tag || "").startsWith("en") && e.value)?.value ?? null;
};
const enAll = (arr) => (arr || []).filter((e) => String(e.language_tag || "en").startsWith("en") && e.value).map((e) => e.value);
const cm = (d) => {
  const s = d?.normalized_value || d;
  const v = Number(s?.value), f = UNIT_TO_CM[String(s?.unit || "").toLowerCase()];
  return Number.isFinite(v) && f ? Math.round(v * f * 10) / 10 : null;
};

function toProduct(item) {
  const title = en(item.item_name);
  if (!title) return null;
  const d = item.item_dimensions || {};
  const node = (item.node || []).map((n) => n.node_name).find(Boolean);
  const color = (item.color || []).find((c) => String(c.language_tag || "en").startsWith("en"));
  return {
    id: `abo:${item.item_id}`,
    source: "abo",
    source_id: item.item_id,
    url: `https://www.${item.domain_name || "amazon.com"}/dp/${item.item_id}`,
    title,
    brand: en(item.brand),
    product_type: item.product_type?.[0]?.value ?? null,
    category: node ? node.replace(/^\/|\/$/g, "").split("/") : [],
    style: en(item.style),
    material: en(item.material),
    color: color?.standardized_values?.[0] ?? color?.value ?? null,
    price: null,
    currency: null,
    description: en(item.product_description) || enAll(item.bullet_point).join(" ") || null,
    image_ids: [item.main_image_id, ...(item.other_image_id || [])].filter(Boolean),
    image_urls: [], // filled by attachImages()
    model_3d_id: item["3dmodel_id"] || null,
    model_3d_url: null, // filled by attachModels()
    width_cm: cm(d.width),
    depth_cm: cm(d.length), // ABO length = front to back
    height_cm: cm(d.height),
    keywords: enAll(item.item_keywords).slice(0, 20),
    caption: null,
    vibe_tags: null,
    license: LICENSE,
    scraped_at: new Date().toISOString(),
  };
}

// Look up image paths for a set of ids by streaming images.csv.gz (image_id,height,width,path). Stops when all found.
async function attachImages(products, size) {
  const want = new Set(products.flatMap((p) => p.image_ids));
  if (!want.size) return;
  const paths = new Map();
  for await (const line of gzLines(`${BASE}/images/metadata/images.csv.gz`)) {
    const id = line.slice(0, line.indexOf(","));
    if (want.has(id)) {
      paths.set(id, line.slice(line.lastIndexOf(",") + 1).trim());
      if (paths.size === want.size) break;
    }
  }
  for (const p of products) p.image_urls = p.image_ids.filter((i) => paths.has(i)).map((i) => `${BASE}/images/${size}/${paths.get(i)}`);
}

async function attachModels(products) {
  const want = new Set(products.map((p) => p.model_3d_id).filter(Boolean));
  if (!want.size) return;
  const paths = new Map();
  let header = null;
  for await (const line of gzLines(`${BASE}/3dmodels/metadata/3dmodels.csv.gz`)) {
    const cols = line.split(",");
    if (!header) { header = cols; continue; }
    const id = cols[header.indexOf("3dmodel_id")], path = cols[header.indexOf("path")];
    if (want.has(id)) { paths.set(id, path); if (paths.size === want.size) break; }
  }
  for (const p of products) if (paths.has(p.model_3d_id)) p.model_3d_url = `${BASE}/3dmodels/original/${paths.get(p.model_3d_id)}`;
}

const TYPE_RE = /"product_type"\s*:\s*\[\s*\{\s*"value"\s*:\s*"([A-Z0-9_]+)"/;

export async function aboProducts({ shard = "0", types = ABO_DEFAULT_TYPES, limit = 50, offset = 0,
  requireDims = false, require3d = false, images = true, imageSize = "small" }) {
  const want = new Set(types);
  const out = [];
  let skipped = 0;
  for await (const line of gzLines(`${BASE}/listings/metadata/listings_${shard}.json.gz`)) {
    const t = line.match(TYPE_RE)?.[1]; // cheap prefilter before JSON.parse
    if (!t || !want.has(t)) continue;
    if (require3d && !line.includes('"3dmodel_id"')) continue;
    const p = toProduct(JSON.parse(line));
    if (!p) continue;
    if (requireDims && (p.width_cm == null || p.depth_cm == null || p.height_cm == null)) continue;
    if (skipped < offset) { skipped++; continue; }
    out.push(p);
    if (out.length >= limit) break;
  }
  if (images) await attachImages(out, imageSize);
  await attachModels(out);
  return out;
}
