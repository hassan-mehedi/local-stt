"""Renders the menu bar icons from SF Symbols into src-tauri/icons/tray.

Run from the repo with: uv run python app/scripts/make_tray_icons.py
"""

from pathlib import Path

from AppKit import (
    NSBitmapImageRep,
    NSColor,
    NSCompositingOperationSourceOver,
    NSGraphicsContext,
    NSImage,
    NSImageSymbolConfiguration,
    NSPNGFileType,
)

OUT = Path(__file__).resolve().parent.parent / "src-tauri" / "icons" / "tray"
PIXELS = 36  # 18 points at 2x

# name -> (SF Symbol, color or None for a black template image)
ICONS = {
    "off": ("mic.slash", None),
    "idle": ("mic", None),
    "recording": ("mic.fill", "systemRedColor"),
    "transcribing": ("waveform", "systemOrangeColor"),
}


def render(symbol: str, color: str | None, dest: Path) -> None:
    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(26, 0.0)
    if color:
        config = config.configurationByApplyingConfiguration_(
            NSImageSymbolConfiguration.configurationWithPaletteColors_([getattr(NSColor, color)()])
        )
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, None)
    image = image.imageWithSymbolConfiguration_(config)
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, PIXELS, PIXELS, 8, 4, True, False, "NSDeviceRGBColorSpace", 0, 0
    )
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    w, h = image.size()
    scale = min(PIXELS / w, PIXELS / h) * 0.9
    dw, dh = w * scale, h * scale
    image.drawInRect_fromRect_operation_fraction_(
        (((PIXELS - dw) / 2, (PIXELS - dh) / 2), (dw, dh)),
        ((0, 0), (0, 0)),
        NSCompositingOperationSourceOver,
        1.0,
    )
    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(str(dest), True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (symbol, color) in ICONS.items():
        render(symbol, color, OUT / f"{name}.png")
        print(OUT / f"{name}.png")
