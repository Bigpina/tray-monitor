"""Generate crayfish tray icon - transparent background."""
from PIL import Image, ImageDraw

def create_lobster(size):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64.0

    body = (200, 40, 20, 255)
    dark = (160, 30, 15, 255)
    bright = (230, 60, 35, 255)
    white = (255, 255, 255, 255)
    black = (30, 30, 30, 255)

    draw.ellipse([18*s, 24*s, 46*s, 50*s], fill=body)
    draw.ellipse([21*s, 16*s, 43*s, 32*s], fill=body)
    draw.ellipse([22*s, 44*s, 42*s, 56*s], fill=dark)
    draw.pieslice([20*s, 50*s, 44*s, 62*s], 0, 180, fill=dark)

    draw.line([(22*s, 28*s), (10*s, 18*s)], fill=body, width=max(int(4*s), 1))
    draw.ellipse([2*s, 8*s, 16*s, 22*s], fill=bright)
    draw.ellipse([4*s, 16*s, 18*s, 28*s], fill=bright)
    draw.line([(5*s, 16*s), (15*s, 16*s)], fill=dark, width=max(int(1.5*s), 1))

    draw.line([(42*s, 28*s), (54*s, 18*s)], fill=body, width=max(int(4*s), 1))
    draw.ellipse([48*s, 8*s, 62*s, 22*s], fill=bright)
    draw.ellipse([46*s, 16*s, 60*s, 28*s], fill=bright)
    draw.line([(49*s, 16*s), (59*s, 16*s)], fill=dark, width=max(int(1.5*s), 1))

    draw.line([(28*s, 20*s), (24*s, 12*s)], fill=body, width=max(int(3*s), 1))
    draw.ellipse([19*s, 6*s, 29*s, 16*s], fill=white)
    draw.ellipse([22*s, 9*s, 26*s, 13*s], fill=black)
    draw.line([(36*s, 20*s), (40*s, 12*s)], fill=body, width=max(int(3*s), 1))
    draw.ellipse([35*s, 6*s, 45*s, 16*s], fill=white)
    draw.ellipse([38*s, 9*s, 42*s, 13*s], fill=black)

    draw.line([(27*s, 14*s), (15*s, 2*s)], fill=dark, width=max(int(2*s), 1))
    draw.line([(37*s, 14*s), (49*s, 2*s)], fill=dark, width=max(int(2*s), 1))

    for y_off in [0, 5*s, 10*s]:
        draw.line([(20*s, (32*s)+y_off), (10*s, (37*s)+y_off)], fill=dark, width=max(int(2*s), 1))
        draw.line([(44*s, (32*s)+y_off), (54*s, (37*s)+y_off)], fill=dark, width=max(int(2*s), 1))

    return img

# Generate 64x64 PNG (pystray will handle sizing)
icon = create_lobster(64)
icon.save(r"D:\openclaw\alpha\tray-monitor\icons\lobster.png")

# Generate ICO with Pillow's auto-resize
icon.save(r"D:\openclaw\alpha\tray-monitor\icons\lobster.ico", format='ICO',
           sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

print("Done - 64x64 source, auto-resized ICO")
