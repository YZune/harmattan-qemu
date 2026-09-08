# Code-drawn frame geometry

[简体中文](frame-geometry.zh-CN.md) · [Optional artwork](README.md)

`HARMATTAN_UI_SKIN=frame` uses [n00-n9-frame.h](../n00-n9-frame.h). Its dimensions come from published device specifications and explicit project design choices. The frame renderer does not load an image or use the optional artwork's crop, aperture, glass mask or key coordinates.

## Sources checked on 2026-09-08

| Source | Facts used | Limits |
| --- | --- | --- |
| [Nokia N9 launch datasheet, mirrored by Mobilepulse](https://mobilepulse.de/wp-content/uploads/2011/06/1-nokia-n9-data-sheet.pdf), page 1 | Body 116.45 × 61.2 mm; thickness 7.6–12.1 mm; nominal 3.9-inch, 854 × 480 display | Nokia-authored product sheet hosted by a third party; not a dimensioned mechanical drawing |
| [Nokia N9 User Guide, Issue 1.0, mirrored by One NZ](https://one.nz/MEDIA_CustomProductCatalog/m5670124_N9_UG_en.pdf), printed page 6 | Earpiece, volume/zoom key, power/lock key and front camera identification | Used for component identities; no diagram paths or pixel coordinates were extracted |
| [Nokia N9 on Wikipedia](https://en.wikipedia.org/wiki/Nokia_N9) | Cross-check of body dimensions, display diagonal and resolution | Secondary source; the implementation uses the datasheet values |

Only the facts and links are recorded here. The source PDFs and their illustrations are not bundled. The thickness is documented for context; this is a front-view illustration, not a three-dimensional model.

## Derived dimensions

Use 10 model units per millimetre. The body rectangle is 612 × 1164.5 units. A project-selected 1 mm margin surrounds it, making the canvas 632 × 1184.5 units; side-key silhouettes fit inside that margin.

Assuming square pixels and using the nominal diagonal:

```text
diagonal_mm = 3.9 × 25.4 = 99.06
screen_width_mm  = diagonal_mm × 480 / sqrt(480² + 854²) ≈ 48.53647
screen_height_mm = diagonal_mm × 854 / sqrt(480² + 854²) ≈ 86.35447
```

These are calculated approximations, not measurements of the panel. The active area is centred in the body as a project layout choice. The full 480 × 864 guest framebuffer is aspect-fitted into it without cropping; its dimensions differ from the retail display. Landscape mode rotates the same geometry and input regions by 90 degrees.

## Project design choices

The checked sources do not specify the following dimensions. These values define a simplified flat illustration; they are not presented as Nokia engineering measurements.

| Element | Chosen construction |
| --- | --- |
| Body | Rounded rectangle with 1.2 mm corners; flat graphite fill and 0.8 mm solid side strips |
| Glass | Body inset 1.8 mm horizontally and 2.8 mm vertically; 3.2 mm corner radius; black fill |
| Earpiece | Centred in the upper body-to-glass gap; width 8.5% of body width, height 0.4 mm |
| Volume silhouette | Right side; starts at 70% of body height from the bottom; length 14% of body height; width 0.7 mm |
| Power/lock silhouette | Right side; centre at 58% of body height from the bottom; length 6.5% of body height; width 0.7 mm |
| Lock hit target | Extends 1.2 mm above/below the key; begins 0.4 mm outside the glass and ends at the canvas edge |
| Front-camera detail | Centre 2.8 mm left of the glass's right edge, halfway between the glass and screen bottoms; 1.8 mm outer diameter |
| Palette and outlines | Project-selected solid grayscale colours; no gradients, textures or logo |

The power/lock key retains its existing action. The volume and camera details are decorative and do not add device functionality. All glass presses continue to route to the guest so edge swipes can begin outside the active screen.

## Separation from optional artwork

The earlier default frame shared the optional PSD skin's layout. This implementation replaces that dependency with the model above. The prior exposure to the PSD remains part of the development history; this is a documented reimplementation, not a claim of a clean-room process.

`n00_n9_geometry()` in [n00-n9-skin.h](../n00-n9-skin.h) selects the new geometry when no image is supplied. Its image-only branch preserves the old 620 × 1160 mapping for user-supplied Livven artwork. That compatibility mapping is not used by the default code-drawn frame, and the artwork's separate permission requirements remain in [the artwork guide](README.md).

The native host test checks the derived display size, body ratio, centred aperture, key containment, fractional scaling, portrait/landscape input and opaque screen matte. It also freezes the legacy artwork mapping independently. Such tests establish implementation behaviour, not a legal clearance or an exact physical replica.
