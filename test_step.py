"""Step-by-step test: find exactly where the icon breaks."""
import pystray
from PIL import Image, ImageDraw

def on_exit(icon, item):
    icon.stop()

# Step 1: Solid red square (we know this works)
img1 = Image.new('RGB', (32, 32), (200, 40, 20))

# Step 2: Load lobster PNG and composite onto dark background
lobster = Image.open(r'D:\openclaw\alpha\tray-monitor\icons\lobster.png').convert('RGBA')
print(f'Lobster: {lobster.size}, mode={lobster.mode}')

bg = Image.new('RGB', (128, 128), (30, 40, 60))
bg.paste(lobster, (0, 0), lobster)
img2 = bg.resize((48, 48), Image.Resampling.LANCZOS)
print(f'Composited: {img2.size}, mode={img2.mode}')

# Step 3: Draw dots on it
draw = ImageDraw.Draw(img2)
draw.ellipse([28, 36, 44, 46], fill=(0, 200, 80))
draw.ellipse([36, 36, 46, 46], fill=(50, 120, 255))
img3 = img2.convert('RGB')
print(f'With dots: {img3.size}, mode={img3.mode}')

# Test each one
import sys
choice = sys.argv[1] if len(sys.argv) > 1 else '1'
if choice == '1':
    test_img = img1
    print("Testing: solid red square")
elif choice == '2':
    test_img = img2
    print("Testing: lobster composite")
else:
    test_img = img3
    print("Testing: lobster with dots")

icon = pystray.Icon(name="test", icon=test_img, title="Test",
    menu=pystray.Menu(pystray.MenuItem("Exit", on_exit)))
icon.run()
