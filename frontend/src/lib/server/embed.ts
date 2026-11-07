/**
 * Query embeddings in Node, matching the product vectors stored in Supabase.
 *
 * Products were embedded in Python with BAAI/bge-small-en-v1.5 (CLS pooling, L2-normalised,
 * see backend/app/services/product/embed.py). This is the same model as ONNX via transformers.js.
 * Checked: cosine 1.000 vs Python at fp32, 0.997 at q8 (the default here: 4x smaller, faster cold start).
 */
import type { FeatureExtractionPipeline } from "@huggingface/transformers";

export const EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5";
export const EMBEDDING_VERSION = "text-v1";
// bge wants this prefix on queries (not on documents)
const QUERY_PREFIX = "Represent this sentence for searching relevant passages: ";

let extractor: Promise<FeatureExtractionPipeline> | null = null;

async function getExtractor(): Promise<FeatureExtractionPipeline> {
  if (!extractor) {
    extractor = (async () => {
      const { pipeline, env } = await import("@huggingface/transformers");
      // serverless file systems are read-only except /tmp
      if (process.env.VERCEL || process.env.AWS_LAMBDA_FUNCTION_NAME) env.cacheDir = "/tmp/transformers-cache";
      const dtype = process.env.EMBEDDING_DTYPE === "fp32" ? "fp32" : "q8";
      return pipeline("feature-extraction", "Xenova/bge-small-en-v1.5", { dtype });
    })();
    extractor.catch(() => {
      extractor = null; // retry the download on the next request
    });
  }
  return extractor;
}

export async function embedQuery(text: string): Promise<number[]> {
  const extract = await getExtractor();
  const output = await extract(QUERY_PREFIX + text, { pooling: "cls", normalize: true });
  return Array.from(output.data as Float32Array);
}
