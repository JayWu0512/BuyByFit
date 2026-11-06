import { test } from "node:test";
import assert from "node:assert/strict";
import { parseProduct } from "../src/scrape.js";
import { dimsFromText, dimsFromSpecs } from "../src/parse/dimensions.js";
import { hdSearchResults, hdIdFromUrl } from "../src/parse/homedepot.js";

const HD_HTML = `<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Mid-Century Modern 3-Seat Sofa in Teal Velvet","brand":{"@type":"Brand","name":"Acme Home"},"sku":"318046582","description":"Tapered walnut legs, tufted back.","image":["https://images.thdstatic.com/a.jpg","https://images.thdstatic.com/b.jpg"],"offers":{"@type":"Offer","price":"649.00","priceCurrency":"USD"},"aggregateRating":{"ratingValue":"4.5","reviewCount":"212"}}</script>
<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[{"position":1,"item":{"name":"Furniture"}},{"position":2,"item":{"name":"Living Room Furniture"}},{"position":3,"item":{"name":"Sofas & Couches"}}]}</script>
</head><body><script>window.__APOLLO_STATE__={"specificationGroup":[{"specifications":[{"specName":"Product Width (in.)","specValue":"84"},{"specName":"Product Depth (in.)","specValue":"36"},{"specName":"Product Height (in.)","specValue":"33"},{"specName":"Seat Height (in.)","specValue":"18"},{"specName":"Package Width (in.)","specValue":"90"},{"specName":"Color Family","specValue":"Teal"}]}]}</script></body></html>`;

test("Home Depot product page -> normalized product", () => {
  const p = parseProduct(HD_HTML, "https://www.homedepot.com/p/Acme-Sofa/318046582");
  assert.equal(p.id, "homedepot:318046582");
  assert.equal(p.title, "Mid-Century Modern 3-Seat Sofa in Teal Velvet");
  assert.equal(p.brand, "Acme Home");
  assert.equal(p.price, 649);
  assert.deepEqual(p.category, ["Furniture", "Living Room Furniture", "Sofas & Couches"]);
  assert.equal(p.image_urls.length, 2);
  assert.equal(p.width_cm, 213.4);
  assert.equal(p.depth_cm, 91.4);
  assert.equal(p.height_cm, 83.8); // not seat height, not package
  assert.equal(p.rating, 4.5);
});

test("generic retailer JSON-LD with @graph", () => {
  const html = `<script type="application/ld+json">{"@graph":[{"@type":"Product","name":"Wardrobe","productID":"W1","image":{"url":"https://x/w.jpg"},"description":"Dimensions: 60x50x192 cm","offers":[{"price":199,"priceCurrency":"USD"}]}]}</script>`;
  const p = parseProduct(html, "https://www.example-store.com/p/w1");
  assert.equal(p.source, "example-store.com");
  assert.equal(p.id, "example-store.com:W1");
  assert.deepEqual([p.width_cm, p.depth_cm, p.height_cm], [60, 50, 192]);
  assert.deepEqual(p.image_urls, ["https://x/w.jpg"]);
});

test("dimension text formats", () => {
  assert.deepEqual(dimsFromText('84 in. W x 36 in. D x 33 in. H'), { width_cm: 213.4, depth_cm: 91.4, height_cm: 83.8 });
  assert.deepEqual(dimsFromText('W 30" x D 20" x H 40"'), { width_cm: 76.2, depth_cm: 50.8, height_cm: 101.6 });
  assert.deepEqual(dimsFromText("No size here"), { width_cm: null, depth_cm: null, height_cm: null });
});

test("spec names with cm units and assembled prefix", () => {
  const d = dimsFromSpecs([{ name: "Assembled Width (cm)", value: "120" }, { name: "Assembled Height (cm)", value: "75" }]);
  assert.equal(d.width_cm, 120);
  assert.equal(d.height_cm, 75);
});

test("search page links -> unique ids", () => {
  const html = `<a href="/p/Acme-Sofa/318046582">x</a><a href="/p/Acme-Sofa/318046582?x=1">dup</a><a href='/p/Oak-Table/205123456'>y</a>`;
  const r = hdSearchResults(html);
  assert.deepEqual(r.map((x) => x.id), ["318046582", "205123456"]);
  assert.equal(r[1].slug_title, "Oak Table");
  assert.equal(hdIdFromUrl("https://www.homedepot.com/p/Thing/123456789?a=b"), "123456789");
});
