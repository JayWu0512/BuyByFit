# BuyByFit design system

## Direction

BuyByFit is an editorial, room-first furniture experience. It uses calm material fields and confident display typography to make product browsing feel considered rather than transactional. The composition should leave room for a visitor's own description and let furniture imagery, material, fit, and source facts work together.

## Visual principles

- **Warm restraint:** paper, oat, sage, and timber fields create hierarchy without relying on dense borders or cards.
- **Clear type hierarchy:** a high-contrast serif introduces moments and room themes; a quiet sans-serif carries controls, facts, and instructions.
- **Soft geometry:** photo frames use intentional asymmetric rounding. Primary choices and related actions use rounded/pill affordances where this softens the interaction; avoid incidental square UI boxes.
- **Full-bleed moments:** major home and discovery sections extend their color field to the viewport edge while their content aligns to the page grid.
- **Truthful interactions:** a result, price, retailer action, progress state, or feedback control must accurately communicate its state and scope.

## Core tokens

| Token | Value | Use |
| --- | --- | --- |
| Paper | `#F7F5F0` | Main page ground |
| Oat | `#E7DED0` | Warm section fields and input context |
| Timber | `#896E54` | Warm accent and secondary action |
| Timber dark | `#65513F` | Deeper accent contrast |
| Sage | `#A1A999` | Discovery and room context |
| Sage pale | `#DCE0D6` | Quiet status/context surfaces |
| Ink | `#292B28` | Primary type and high-contrast actions |
| Surface | `#FFFFFF` | Elevated input/media surface |

The source of truth is the CSS custom properties in `src/app/globals.css`; use those tokens rather than introducing near-duplicate colors.

## Interaction conventions

- Preserve visible keyboard focus for every control.
- Keep primary and secondary actions visually related when they offer alternatives in the same step.
- Explain optional capabilities near the action (for example camera access or room measurements), not as permanent product marketing copy.
- Let long room briefs wrap naturally on smaller screens; do not reduce the hierarchy just to force one line.
- Design for a comfortable touch target and test responsive layouts before merging.

## Image and brand assets

`public/images/` holds fictional demonstration imagery and `public/brand-mark.svg` is the vector source for the brand mark. `public/brand-mark.png` and `public/brand-mark-3x2.png` are supplied raster variants for platforms that require PNG, including a 3:2 upload requirement.

Demo imagery establishes a placeholder visual system only. A live catalogue must use appropriately licensed source images and preserve the retailer/product context attached to each record.
