/**
 * Room brief -> search hints. "a cozy mid-century sofa that fits 230 by 100" becomes
 * { vibe: "a cozy mid-century sofa", types: ["SOFA"], maxWidthCm: 230, maxDepthCm: 100 }.
 *
 * Mirrors parse_query() in ar-mvp/server.py so the web app and the AR demo read briefs the same way.
 */

export interface BriefHints {
  vibe: string;
  types: string[] | null;
  typeLabel: string | null;
  maxWidthCm: number | null;
  maxDepthCm: number | null;
  maxHeightCm: number | null;
}

const NUM = String.raw`(\d+(?:\.\d+)?)`;
// longest spellings first, so "meters" isn't read as "m" + "eters"
const UNIT = String.raw`(centimet(?:er|re)s?|millimet(?:er|re)s?|met(?:er|re)s?|inch(?:es)?|feet|foot|cm\b|mm\b|m\b|in\b|ft\b|"|')`;

// first match wins; order matters ("bean bag" before "chair", "teddy bear" before "bear")
const TYPE_WORDS: [RegExp, string[], string][] = [
  [/\b(teddy( bears?)?|teddies|plush(ies|ie|y)?|stuffed (animals?|toys?)|stuffies?|soft toys?|toys?|dolls?)\b/, ["PLUSH_TOY"], "plush toy"],
  [/\b(bean ?bags?( chairs?)?)\b/, ["BEAN_BAG_CHAIR"], "bean bag"],
  [/\b((throw )?pillows?|cushions?)\b/, ["PILLOW"], "pillow"],
  [/\b(planters?|plant pots?|plants?|succulents?)\b/, ["PLANTER", "ARTIFICIAL_PLANT"], "planter"],
  [/\b(vases?)\b/, ["VASE"], "vase"],
  [/\b(candle ?holders?|candlesticks?)\b/, ["CANDLE_HOLDER"], "candle holder"],
  [/\b(chandeliers?|pendants?|ceiling lights?)\b/, ["LIGHT_FIXTURE"], "light fixture"],
  [/\b(sofas?|couch(es)?|loveseats?|sectionals?|settees?)\b/, ["SOFA"], "sofa"],
  [/\b(arm ?chairs?|recliners?|chairs?)\b/, ["CHAIR"], "chair"],
  [/\b(desks?)\b/, ["DESK"], "desk"],
  [/\b((coffee |side |end |dining )?tables?|nightstands?)\b/, ["TABLE"], "table"],
  [/\b((floor |table |desk )?lamps?)\b/, ["LAMP"], "lamp"],
  [/\b(rugs?|carpets?)\b/, ["RUG"], "rug"],
  [/\b(ottomans?|poufs?|footstools?)\b/, ["OTTOMAN"], "ottoman"],
  [/\b(stools?)\b/, ["STOOL_SEATING"], "stool"],
  [/\b(shel(f|ves)|bookcases?|bookshel(f|ves))\b/, ["SHELF"], "shelf"],
  [/\b(cabinets?|sideboards?|credenzas?|tv stands?|media consoles?)\b/, ["CABINET", "HOME_FURNITURE_AND_DECOR"], "cabinet"],
  [/\b(dressers?|chest of drawers)\b/, ["DRESSER", "HOME_FURNITURE_AND_DECOR"], "dresser"],
  [/\b(beds?|bed ?frames?|headboards?)\b/, ["BED", "BED_FRAME", "HEADBOARD"], "bed"],
  [/\b(bench(es)?)\b/, ["BENCH"], "bench"],
];

function unitToCm(unit: string | undefined): number | null {
  if (!unit) return null;
  const u = unit.toLowerCase();
  if (u === '"' || u.startsWith("in")) return 2.54;
  if (u === "'" || u.startsWith("ft") || u.startsWith("fe") || u.startsWith("fo")) return 30.48;
  if (u.startsWith("mm") || u.startsWith("milli")) return 0.1;
  if (u.startsWith("cm") || u.startsWith("centi")) return 1;
  if (u.startsWith("m")) return 100;
  return null;
}

function toCm(nums: number[], unit: string | undefined): number[] {
  // no unit said: small numbers are metres ("2 by 1"), otherwise centimetres
  const factor = unitToCm(unit) ?? (Math.max(...nums) < 10 ? 100 : 1);
  return nums.map((n) => Math.round(n * factor * 10) / 10);
}

export function parseBrief(text: string): BriefHints {
  const t = text.toLowerCase().replace(/×/g, "x");
  const out: BriefHints = { vibe: t, types: null, typeLabel: null, maxWidthCm: null, maxDepthCm: null, maxHeightCm: null };
  let vibe = t;

  const sep = String.raw`\s*(?:by|x|\*)\s*`;
  const pair = new RegExp(`${NUM}\\s*${UNIT}?${sep}${NUM}\\s*${UNIT}?(?:${sep}${NUM}\\s*${UNIT}?)?`);
  const m = t.match(pair);
  if (m) {
    const nums = [m[1], m[3], m[5]].filter(Boolean).map(Number);
    const cm = toCm(nums, m[6] ?? m[4] ?? m[2]);
    [out.maxWidthCm, out.maxDepthCm] = [cm[0], cm[1]];
    if (cm.length > 2) out.maxHeightCm = cm[2];
    vibe = vibe.replace(m[0], " ");
  }

  const axes: ["maxWidthCm" | "maxDepthCm" | "maxHeightCm", string][] = [
    ["maxWidthCm", "wide|width|long|length"],
    ["maxDepthCm", "deep|depth"],
    ["maxHeightCm", "tall|high|height"],
  ];
  for (const [key, words] of axes) {
    const a = t.match(new RegExp(`${NUM}\\s*${UNIT}?\\s*(?:${words})\\b`));
    if (a && out[key] === null) {
      out[key] = toCm([Number(a[1])], a[2])[0];
      vibe = vibe.replace(a[0], " ");
    }
  }

  for (const [pattern, types, label] of TYPE_WORDS) {
    if (pattern.test(t)) {
      out.types = types;
      out.typeLabel = label;
      break;
    }
  }

  vibe = vibe.replace(/\b(that |which |to )?(fits?|fitting|under|less than|at most|max(imum)?)\b/g, " ");
  out.vibe = vibe.replace(/\s+/g, " ").replace(/^[\s,.]+|[\s,.]+$/g, "") || text;
  return out;
}
