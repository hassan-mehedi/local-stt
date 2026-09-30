"""Draws the app icon (SF Symbol mic on a rounded tile) and writes
icon.icns next to this file. Run with: uv run packaging/macos/make_icon.py"""

import subprocess
import tempfile
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSGradient,
    NSGraphicsContext,
    NSImage,
    NSImageSymbolConfiguration,
    NSMakeRect,
)

HERE = Path(__file__).parent


def draw(size: int) -> bytes:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, "NSDeviceRGBColorSpace", 0, 0
    )
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))

    # Apple's icon grid: an 824pt tile centred in 1024
    inset = size * 100 / 1024
    tile = NSMakeRect(inset, inset, size - 2 * inset, size - 2 * inset)
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        tile, size * 0.18, size * 0.18
    )
    NSGradient.alloc().initWithStartingColor_endingColor_(
        NSColor.colorWithSRGBRed_green_blue_alpha_(0.20, 0.55, 1.0, 1),
        NSColor.colorWithSRGBRed_green_blue_alpha_(0.35, 0.20, 0.85, 1),
    ).drawInBezierPath_angle_(path, -90)

    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(size * 0.42, 0.3)
    config = config.configurationByApplyingConfiguration_(
        NSImageSymbolConfiguration.configurationWithPaletteColors_([NSColor.whiteColor()])
    )
    mic = NSImage.imageWithSystemSymbolName_accessibilityDescription_("mic.fill", None)
    mic = mic.imageWithSymbolConfiguration_(config)
    w, h = mic.size()
    mic.drawInRect_(NSMakeRect((size - w) / 2, (size - h) / 2, w, h))

    NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {}))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                suffix = "@2x" if scale == 2 else ""
                (iconset / f"icon_{points}x{points}{suffix}.png").write_bytes(draw(points * scale))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)


if __name__ == "__main__":
    main()
