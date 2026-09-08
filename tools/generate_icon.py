from pathlib import Path

from PIL import Image, ImageDraw


root = Path(__file__).resolve().parents[1]
size = 256
image = Image.new("RGBA", (size, size), (16, 19, 24, 255))
draw = ImageDraw.Draw(image)

# Rounded dark tile and mint clipboard mark.
draw.rounded_rectangle((12, 12, 244, 244), radius=55, fill=(23, 27, 34, 255))
draw.rounded_rectangle((62, 55, 194, 211), radius=23, fill=(120, 214, 198, 255))
draw.rounded_rectangle((92, 38, 164, 78), radius=15, fill=(243, 245, 247, 255))
draw.rounded_rectangle((81, 92, 175, 109), radius=8, fill=(28, 66, 61, 255))
draw.rounded_rectangle((81, 128, 175, 145), radius=8, fill=(28, 66, 61, 255))
draw.rounded_rectangle((81, 164, 148, 181), radius=8, fill=(28, 66, 61, 255))

image.save(root / "clipboard_library.ico", sizes=[(16, 16), (24, 24), (32, 32),
                                                   (48, 48), (64, 64), (128, 128),
                                                   (256, 256)])
