# BuyByFit product brief

## Product promise

BuyByFit helps someone start with the room they have—not a retailer's filter menu—and discover furniture that supports the way they want to live. The experience should feel editorial and calm while still making practical facts easy to compare.

## Core journey

1. A visitor describes their room in ordinary language, optionally using voice.
2. They add a budget and can express dimensions or fit requirements in the brief.
3. The app returns ranked pieces from the configured catalogue, with price, dimensions, material, source, and match context where data is available.
4. They open a product detail page, visit the retailer when a verified source URL exists, or use a supplied 3D/AR asset when available.
5. They may upload/take a room photo to request a restyled preview. This is an asynchronous optional capability, not a promise of exact architectural measurement.

## Product principles

- **Room first.** A brief should describe feeling, light, materials, daily use, dimensions, budget, and constraints in a natural sentence.
- **Honest source data.** A retailer URL, price, availability, product image, and 3D asset may change. Missing or estimated data must never be presented as verified.
- **Practical comparison.** Keep dimensions, price/estimate, materials, and retailer context legible alongside the visual direction.
- **Graceful capability.** Search always works with the local demo catalogue; live-catalogue search and room visualization activate only when their server-side integrations are configured.
- **Respectful media handling.** Room images are used for the requested visualization flow and are not treated as public catalogue assets.
- **Low-friction exploration.** Preserve a visitor's search and sorting state while they inspect a product or room render.

## Current boundaries

- No checkout, cart, payment, account, or inventory reservation is implemented.
- `Buy it` is an outbound retailer link, not a transaction in BuyByFit.
- The fictional bundled catalogue is for local/demo resilience only.
- Room renders depend on an external AI pipeline; result quality and processing time vary with the source image and available service capacity.
