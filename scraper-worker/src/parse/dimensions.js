// Normalize furniture dimensions to centimeters.
// Sources: (1) spec name/value pairs, (2) free text like "84 in. W x 36 in. D x 33 in. H" or "60x50x192 cm".

const IN_TO_CM = 2.54;
const round = (n) => (n == null || Number.isNaN(n) ? null : Math.round(n * 10) / 10);

function toCm(value, unit) {
  const n = parseFloat(String(value).replace(/,/g, ""));
  if (Number.isNaN(n)) return null;
  const u = (unit || "").toLowerCase();
  if (u.startsWith("in") || u === '"' || u === "″") return n * IN_TO_CM;
  if (u.startsWith("ft") || u === "'") return n * 30.48;
  if (u.startsWith("mm")) return n / 10;
  if (u === "m") return n * 100;
  return n; // cm or unknown -> assume cm
}

const PACKAGE_WORDS = /(package|packaging|box|shipping|carton|seat|arm|leg|back|drawer|shelf|opening|interior|clearance)/i;

// specs: [{ name, value }]
export function dimsFromSpecs(specs = []) {
  const out = { width_cm: null, depth_cm: null, height_cm: null };
  const pick = (re) => {
    const hit = specs.find((s) => re.test(s.name) && !PACKAGE_WORDS.test(s.name));
    if (!hit) return null;
    const unitMatch = hit.name.match(/\((in|cm|mm|ft|m)\.?\)/i) || String(hit.value).match(/\b(in|cm|mm|ft)\b|"/i);
    const unit = unitMatch ? (unitMatch[1] || unitMatch[0]) : "in"; // US retailers default to inches
    return toCm(String(hit.value).match(/[\d.,]+/)?.[0], unit);
  };
  out.width_cm = round(pick(/(assembled|product|overall)?\s*width/i));
  out.depth_cm = round(pick(/(assembled|product|overall)?\s*(depth|length)/i));
  out.height_cm = round(pick(/(assembled|product|overall)?\s*height/i));
  return out;
}

// Free text, e.g. 'W 30" x D 20" x H 40"', '84 in. W x 36 in. D x 33 in. H', '60x50x192 cm'
export function dimsFromText(text = "") {
  const t = String(text);
  const out = { width_cm: null, depth_cm: null, height_cm: null };

  // Labeled: number unit? letter  OR  letter number unit?
  const labeled = [
    ...t.matchAll(/([\d.]+)\s*(in\.?|inches|"|cm|mm)?\s*\(?\s*(W|D|H|L)\b\)?/gi),
    ...t.matchAll(/\b(W|D|H|L)\s*[:=]?\s*([\d.]+)\s*(in\.?|inches|"|cm|mm)?/gi),
  ];
  for (const m of labeled) {
    const [num, unit, axis] = /^\d|^\./.test(m[1]) ? [m[1], m[2], m[3]] : [m[2], m[3], m[1]];
    const key = { W: "width_cm", D: "depth_cm", L: "depth_cm", H: "height_cm" }[axis.toUpperCase()];
    if (key && out[key] == null) out[key] = round(toCm(num, unit || "in"));
  }
  if (out.width_cm != null || out.height_cm != null) return out;

  // Unlabeled triple/pair: 60x50x192 cm  (assumed W x D x H)
  const m = t.match(/([\d.]+)\s*[x×]\s*([\d.]+)(?:\s*[x×]\s*([\d.]+))?\s*(cm|mm|in\.?|inches|")/i);
  if (m) {
    const unit = m[4];
    out.width_cm = round(toCm(m[1], unit));
    if (m[3]) {
      out.depth_cm = round(toCm(m[2], unit));
      out.height_cm = round(toCm(m[3], unit));
    } else {
      out.depth_cm = round(toCm(m[2], unit));
    }
  }
  return out;
}

export function mergeDims(...candidates) {
  const out = { width_cm: null, depth_cm: null, height_cm: null };
  for (const c of candidates) for (const k of Object.keys(out)) if (out[k] == null && c?.[k] != null) out[k] = c[k];
  return out;
}
