#!/usr/bin/env python3
"""Export Livven's existing N9 pixels, not a newly rendered device drawing.

Optional asset preparation only: psd-tools==1.19.0, Pillow, numpy.
The QEMU build and runtime use the checked-in PNG without these dependencies.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from psd_tools import PSDImage
from psd_tools.constants import Resource


def hide_logo_and_gloss(psd, merged):
    """Hide the two requested layers and restore their original Glass backing."""
    layers = {layer.name: layer for layer in psd.find("Body")}

    def canvas(layer):
        image = Image.new("RGBA", psd.size)
        image.paste(layer.topil(apply_icc=False), (layer.left, layer.top))
        return np.array(image)

    glass, gloss, logo = (canvas(layers[name]) for name in ("Glass", "Gloss", "Logo"))
    assert layers["Gloss"].clipping and layers["Gloss"].opacity == 64
    assert np.all(glass[:, :, :3][glass[:, :, 3] > 0] == 0)
    assert np.all(gloss[:, :, :3][gloss[:, :, 3] > 0] == 255)
    coverage = (glass[:, :, 3] / 255) * (gloss[:, :, 3] / 255)
    gloss_pixels = coverage > 0
    logo_pixels = logo[:, :, 3] > 0
    assert np.all(glass[:, :, 3][logo_pixels] == 255)
    # These later artwork groups must not be touched by the removed gloss.
    for name in ("Screen (480x854 @2x)", "Camera", "Earpiece", "Buttons"):
        left, top, right, bottom = psd.find(name).bbox
        assert not gloss_pixels[top:bottom, left:right].any()

    rgb = np.array(merged).copy()
    # The source Glass is opaque black beneath the logo and both highlights.
    # At its antialiased perimeter, remove the clipped white overlay only.
    edge = gloss_pixels & (glass[:, :, 3] < 255)
    rgb[edge] = np.clip(np.rint(
        rgb[edge] - coverage[edge, None] * layers["Gloss"].opacity
    ), 0, 255).astype("uint8")
    solid = (gloss_pixels & (glass[:, :, 3] == 255)) | logo_pixels
    rgb[solid] = glass[:, :, :3][solid]
    selected = gloss_pixels | logo_pixels
    assert np.array_equal(rgb[~selected], np.array(merged)[~selected])
    layers["Logo"].visible = False
    layers["Gloss"].visible = False
    return Image.fromarray(rgb), selected


def export(source: Path, destination: Path, hide_details=False, edited_psd=None):
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_sha != "3a6facb79dfdec9d5b22b0d88e866ad491eb703bfb0af670f264840f3079e269":
        raise ValueError("Not the verified Nokia N9.psd from Livven's original ZIP")
    psd = PSDImage.open(source)
    crop = (80, 240, 1320, 2560)
    screen = psd.find("Screen (480x854 @2x)")
    assert screen.bbox == (220, 546, 1180, 2254)
    artwork = {"Body", "Camera", "Earpiece", "Buttons"}

    def include(layer):
        top = layer
        while top.parent is not psd:
            top = top.parent
        return layer.is_visible() and top.name in artwork

    # The layer compositor cannot reproduce every old Photoshop gradient.
    # Use it ONLY for the existing silhouette's alpha, never its RGB output.
    mask = psd.composite(viewport=crop, layer_filter=include, ignore_preview=True)
    alpha = np.array(mask.getchannel("A"))
    merged = psd.topil(apply_icc=False)
    original = np.array(merged.crop(crop).convert("RGB"))
    changed_layers = np.zeros((crop[3]-crop[1], crop[2]-crop[0]), dtype=bool)
    if hide_details:
        merged, selected = hide_logo_and_gloss(psd, merged)
        changed_layers = selected[crop[1]:crop[3], crop[0]:crop[2]]
    rgb = np.array(merged.crop(crop).convert("RGB"))
    matte = np.array(merged.getpixel((0, 0)))
    assert tuple(matte) == (224, 224, 224)
    opacity = alpha.astype(float) / 255
    edge = (alpha > 0) & (alpha < 255)
    # Undo the known presentation matte at the antialiased perimeter only.
    rgb[edge] = np.clip(np.rint(
        (rgb[edge] - (1 - opacity[edge, None]) * matte) / opacity[edge, None]
    ), 0, 255).astype("uint8")
    left, top, right, bottom = screen.bbox
    alpha[top-crop[1]:bottom-crop[1], left-crop[0]:right-crop[0]] = 0
    preserved = (alpha == 255) & ~changed_layers
    assert np.array_equal(rgb[preserved], original[preserved])
    rgba = np.dstack((rgb, alpha))
    rgba[alpha == 0, :3] = 0
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / "n9-black-livven.png"
    Image.fromarray(rgba).save(
        output, icc_profile=psd.image_resources.get_data(Resource.ICC_PROFILE, b"")
    )
    manifest = {
        "author": "Liwen Guo (Livven)",
        "source": "http://livven.me/psds/nokia-n9-psd/",
        "source_zip_sha256": "9a4b5de856d34535b51705746f37f59a34cbbc0d82518e173ddd3c1cc65bec77",
        "source_psd_sha256": source_sha,
        "png_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "psd_canvas": list(psd.size),
        "crop_ltrb": list(crop),
        "screen_ltrb_in_psd": list(screen.bbox),
        "png_size": list(mask.size),
        "model_size": [620, 1160],
        "screen_rect_cocoa": [70, 153, 480, 854],
        "visible_artwork_groups": sorted(artwork),
        "hidden_layers": ["Body/Logo", "Body/Gloss"] if hide_details else [],
        "opaque_artwork_pixels_preserved_exactly": int(preserved.sum()),
        "edited_artwork_pixels": int(np.any(rgb != original, axis=2)[alpha == 255].sum()),
        "unmatted_perimeter_pixels": int(edge.sum()),
    }
    if edited_psd:
        if not hide_details or edited_psd.resolve() == source.resolve():
            raise ValueError("Edited PSD must be a separate file with the two layers hidden")
        # Preserve all layer data/styles. Bypass save()'s automatic gradient
        # recomposition and provide the source-pixel preview explicitly.
        psd._record.image_data.set_data(
            [channel.tobytes() for channel in merged.split()], psd._record.header
        )
        edited_psd.parent.mkdir(parents=True, exist_ok=True)
        with edited_psd.open("wb") as output_psd:
            psd._record.write(output_psd)
        manifest["edited_psd_sha256"] = hashlib.sha256(edited_psd.read_bytes()).hexdigest()
    (destination / "n9-black-livven.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("psd", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--hide-logo-and-gloss", action="store_true")
    parser.add_argument("--edited-psd", type=Path)
    args = parser.parse_args()
    export(args.psd, args.output, args.hide_logo_and_gloss, args.edited_psd)
