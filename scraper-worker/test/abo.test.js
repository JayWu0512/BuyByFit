import { test } from "node:test";
import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import { aboProducts } from "../src/abo.js";

const SOFA = {
  item_id: "B075X4QMX3", domain_name: "amazon.com", "3dmodel_id": "B075X4QMX3",
  item_name: [{ language_tag: "de_DE", value: "Sofa" }, { language_tag: "en_US", value: "Rivet Revolve Modern Sofa" }],
  product_type: [{ value: "SOFA" }],
  item_dimensions: {
    width: { unit: "inches", value: 87, normalized_value: { unit: "inches", value: 87 } },
    length: { unit: "inches", value: 37.75, normalized_value: { unit: "inches", value: 37.75 } },
    height: { unit: "inches", value: 33, normalized_value: { unit: "inches", value: 33 } },
  },
  main_image_id: "IMG1", other_image_id: ["IMG2"],
  node: [{ node_id: 1, node_name: "/Furniture/Living Room/Sofas" }],
};
const NO_DIMS_CHAIR = { item_id: "B0CHAIR", item_name: [{ language_tag: "en_US", value: "Chair" }], product_type: [{ value: "CHAIR" }] };
const CASE = { item_id: "B0CASE", item_name: [{ language_tag: "en_US", value: "Case" }], product_type: [{ value: "CELLULAR_PHONE_CASE" }] };

const FILES = {
  "listings/metadata/listings_0.json.gz": [CASE, NO_DIMS_CHAIR, SOFA].map((x) => JSON.stringify(x)).join("\n"),
  "images/metadata/images.csv.gz": "image_id,height,width,path\nIMG0,1,1,00/x.jpg\nIMG1,256,256,8c/8ccb.jpg\nIMG2,256,256,aa/aa11.jpg\n",
  "3dmodels/metadata/3dmodels.csv.gz": "3dmodel_id,path,meshes\nB075X4QMX3,3/B075X4QMX3.glb,1\n",
};

globalThis.fetch = async (url) => {
  const key = String(url).split(".amazonaws.com/")[1];
  if (!(key in FILES)) return new Response("nope", { status: 404 });
  return new Response(gzipSync(Buffer.from(FILES[key])));
};

test("ABO shard -> furniture products with images and 3D model", async () => {
  const all = await aboProducts({ shard: "0" });
  assert.deepEqual(all.map((p) => p.source_id), ["B0CHAIR", "B075X4QMX3"]);
  const sofa = all[1];
  assert.equal(sofa.title, "Rivet Revolve Modern Sofa");
  assert.deepEqual([sofa.width_cm, sofa.depth_cm, sofa.height_cm], [221, 95.9, 83.8]);
  assert.deepEqual(sofa.image_urls, [
    "https://amazon-berkeley-objects.s3.amazonaws.com/images/small/8c/8ccb.jpg",
    "https://amazon-berkeley-objects.s3.amazonaws.com/images/small/aa/aa11.jpg",
  ]);
  assert.equal(sofa.model_3d_url, "https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/3/B075X4QMX3.glb");
  assert.deepEqual(sofa.category, ["Furniture", "Living Room", "Sofas"]);
});

test("filters: dims, 3d, types, limit, offset", async () => {
  assert.deepEqual((await aboProducts({ shard: "0", requireDims: true })).map((p) => p.source_id), ["B075X4QMX3"]);
  assert.deepEqual((await aboProducts({ shard: "0", require3d: true })).map((p) => p.source_id), ["B075X4QMX3"]);
  assert.deepEqual((await aboProducts({ shard: "0", types: ["CHAIR"] })).map((p) => p.source_id), ["B0CHAIR"]);
  assert.equal((await aboProducts({ shard: "0", limit: 1 })).length, 1);
  assert.deepEqual((await aboProducts({ shard: "0", offset: 1 })).map((p) => p.source_id), ["B075X4QMX3"]);
});
