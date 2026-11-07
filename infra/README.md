# Infrastructure

No infrastructure stack is required for the current self-contained frontend MVP. Run the web app locally from `frontend/` with `npm run dev`.

When the production search, catalogue, and room services are selected, add the chosen local-development and deployment configuration here (for example Compose, Terraform, or Kubernetes). The design must account for:

- a relational database for products, room metadata, and job status;
- a vector database for semantic recommendation retrieval;
- a queue or job mechanism if room/3D processing is asynchronous;
- the external 3D provider, which retains uploaded and generated binary assets.

Keep secrets, persistent database volumes, generated 3D assets, and provider credentials out of Git. The intended service boundaries are described in [the architecture note](../docs/architecture.md).
