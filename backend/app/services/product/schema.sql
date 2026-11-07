-- Product catalog + vibe embeddings (Supabase / Postgres + pgvector).
-- Owner: Diwas (A, product service). Safe to re-run.
--
-- products            : full normalized record, source of truth (WORKFLOW.md rule)
-- product_embeddings  : versioned vectors; one row per (product, model, version)
--                       so a new model can be added without dropping the old one.

create extension if not exists vector;

create table if not exists products (
    id            text primary key,              -- "abo:B075X4QMX3"
    source        text not null,                 -- "abo"
    source_id     text not null,
    url           text,
    title         text not null,
    brand         text,
    product_type  text,                          -- SOFA, CHAIR, ...
    category      text[],
    style         text,
    material      text,
    color         text,
    price         numeric,
    currency      text,
    description   text,
    keywords      text[],
    image_urls    text[],
    model_3d_url  text,                          -- .glb for the 3D service
    width_cm      real,
    depth_cm      real,
    height_cm     real,
    caption       text,                          -- filled by enrich step (vision LLM), later
    vibe_tags     text[],                        -- fixed vocabulary, later
    license       text,
    scraped_at    timestamptz,
    updated_at    timestamptz not null default now()
);

-- web/AR-ready copy of model_3d_url (compressed: 1K textures + Draco), set by ar-mvp/prepare_models.py
alter table products add column if not exists ar_model_url text;

create index if not exists products_type_idx on products (product_type);
create index if not exists products_dims_idx on products (width_cm, depth_cm, height_cm);

create table if not exists product_embeddings (
    product_id         text not null references products(id) on delete cascade,
    embedding_model    text not null,            -- "BAAI/bge-small-en-v1.5"
    embedding_version  text not null,            -- "text-v1": bump when the vibe document changes
    vibe_document      text not null,            -- exact text that was embedded
    embedding          vector(384) not null,
    created_at         timestamptz not null default now(),
    primary key (product_id, embedding_model, embedding_version)
);

create index if not exists product_embeddings_hnsw
    on product_embeddings using hnsw (embedding vector_cosine_ops);

-- Supabase exposes the public schema over its REST API to anyone with the publishable key.
-- Catalog data is public (CC BY 4.0), so allow reads; writes only via the direct DB connection.
alter table products enable row level security;
alter table product_embeddings enable row level security;
drop policy if exists products_public_read on products;
create policy products_public_read on products for select using (true);
drop policy if exists product_embeddings_public_read on product_embeddings;
create policy product_embeddings_public_read on product_embeddings for select using (true);

-- Vibe search with a room-fit filter. Unknown dims never pass a fit filter.
-- Example: select * from match_products('<query vector>', 230, 100, null, array['SOFA'], 10);
drop function if exists match_products(vector, real, real, real, text[], int, text, text);
create or replace function match_products(
    query_embedding vector(384),
    max_width_cm    real    default null,
    max_depth_cm    real    default null,
    max_height_cm   real    default null,
    types           text[]  default null,
    match_count     int     default 10,
    model           text    default 'BAAI/bge-small-en-v1.5',
    version         text    default 'text-v1',
    require_ar      boolean default false
)
returns table (
    id text, title text, product_type text, style text, color text,
    width_cm real, depth_cm real, height_cm real,
    image_url text, model_3d_url text, ar_model_url text, url text, similarity real
)
language sql stable
-- keep scanning the HNSW graph until enough rows pass the fit/type filters (pgvector >= 0.8)
set hnsw.iterative_scan = relaxed_order
as $$
    select p.id, p.title, p.product_type, p.style, p.color,
           p.width_cm, p.depth_cm, p.height_cm,
           p.image_urls[1], p.model_3d_url, p.ar_model_url, p.url,
           (1 - (e.embedding <=> query_embedding))::real as similarity
    from product_embeddings e
    join products p on p.id = e.product_id
    where e.embedding_model = model
      and e.embedding_version = version
      and (max_width_cm  is null or p.width_cm  <= max_width_cm)
      and (max_depth_cm  is null or p.depth_cm  <= max_depth_cm)
      and (max_height_cm is null or p.height_cm <= max_height_cm)
      and (types is null or p.product_type = any(types))
      and (not require_ar or p.ar_model_url is not null)
    order by e.embedding <=> query_embedding
    limit match_count;
$$;
