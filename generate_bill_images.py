"""
Generate 12 realistic synthetic restaurant bill images with visual effects
matching each test case condition (dim light, crumpled, faded thermal, etc.)
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops
import json
from pathlib import Path
import random
import math

class BillImageGenerator:
    """Generate realistic restaurant receipt images with various visual conditions"""
    
    def __init__(self, width=600, height=800):
        self.width = width
        self.height = height
        self.bg_color = (255, 255, 255)
        self.text_color = (0, 0, 0)
        
    def load_bill_data(self, json_path):
        """Load bill data from JSON file"""
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def create_base_receipt(self, data):
        """Create a clean, standard receipt image"""
        img = Image.new('RGB', (self.width, self.height), self.bg_color)
        draw = ImageDraw.Draw(img)
        
        # Try to use a monospace font, fallback to default
        try:
            font_large = ImageFont.truetype("consola.ttf", 28)
            font_med = ImageFont.truetype("consola.ttf", 22)
            font_small = ImageFont.truetype("consola.ttf", 18)
            font_tiny = ImageFont.truetype("consola.ttf", 14)
        except:
            font_large = ImageFont.load_default()
            font_med = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_tiny = ImageFont.load_default()
        
        y = 40
        
        # Restaurant name (centered, bold-ish)
        restaurant = data.get('restaurant_name', 'Restaurant')
        bbox = draw.textbbox((0, 0), restaurant, font=font_large)
        x_center = (self.width - (bbox[2] - bbox[0])) // 2
        draw.text((x_center, y), restaurant, fill=self.text_color, font=font_large)
        y += 50
        
        # Bill number and date
        bill_num = data.get('bill_number', '')
        date = data.get('date', '')
        if bill_num:
            draw.text((50, y), f"Bill: {bill_num}", fill=self.text_color, font=font_tiny)
        if date:
            draw.text((self.width - 200, y), f"Date: {date}", fill=self.text_color, font=font_tiny)
        y += 40
        
        # Divider line
        draw.line([(40, y), (self.width - 40, y)], fill=(100, 100, 100), width=2)
        y += 25
        
        # Items header
        draw.text((50, y), "ITEM", fill=self.text_color, font=font_small)
        draw.text((350, y), "QTY", fill=self.text_color, font=font_small)
        draw.text((450, y), "PRICE", fill=self.text_color, font=font_small)
        y += 30
        
        draw.line([(40, y), (self.width - 40, y)], fill=(150, 150, 150), width=1)
        y += 20
        
        # Items
        for item in data.get('items', []):
            name = item['name']
            qty = item['quantity']
            price = item['total_price']
            
            # Wrap long item names
            if len(name) > 30:
                name = name[:27] + "..."
            
            draw.text((50, y), name, fill=self.text_color, font=font_small)
            draw.text((360, y), f"{qty:.0f}x" if qty > 1 else "1", fill=self.text_color, font=font_small)
            draw.text((450, y), f"₹{price:.2f}", fill=self.text_color, font=font_small)
            y += 28
        
        y += 10
        draw.line([(40, y), (self.width - 40, y)], fill=(100, 100, 100), width=2)
        y += 25
        
        # Subtotal
        subtotal = data.get('subtotal', 0)
        draw.text((50, y), "SUBTOTAL", fill=self.text_color, font=font_small)
        draw.text((450, y), f"₹{subtotal:.2f}", fill=self.text_color, font=font_small)
        y += 35
        
        # Taxes
        taxes = data.get('taxes', {})
        if taxes.get('cgst', 0) > 0:
            draw.text((50, y), f"CGST (2.5%)", fill=self.text_color, font=font_tiny)
            draw.text((450, y), f"₹{taxes['cgst']:.2f}", fill=self.text_color, font=font_tiny)
            y += 25
        if taxes.get('sgst', 0) > 0:
            draw.text((50, y), f"SGST (2.5%)", fill=self.text_color, font=font_tiny)
            draw.text((450, y), f"₹{taxes['sgst']:.2f}", fill=self.text_color, font=font_tiny)
            y += 25
        
        # Service charge
        sc = data.get('service_charge', 0)
        if sc > 0:
            draw.text((50, y), "SERVICE CHARGE (10%)", fill=self.text_color, font=font_tiny)
            draw.text((450, y), f"₹{sc:.2f}", fill=self.text_color, font=font_tiny)
            y += 25
        
        # Discount
        disc = data.get('discount', 0)
        if disc > 0:
            draw.text((50, y), "DISCOUNT", fill=(200, 0, 0), font=font_tiny)
            draw.text((450, y), f"-₹{disc:.2f}", fill=(200, 0, 0), font=font_tiny)
            y += 25
        
        # Tip
        tip = data.get('tip', 0)
        if tip > 0:
            draw.text((50, y), "TIP", fill=self.text_color, font=font_tiny)
            draw.text((450, y), f"₹{tip:.2f}", fill=self.text_color, font=font_tiny)
            y += 25
        
        # Round off
        roff = data.get('round_off', 0)
        if abs(roff) > 0.001:
            draw.text((50, y), "ROUND OFF", fill=self.text_color, font=font_tiny)
            draw.text((450, y), f"₹{roff:.2f}", fill=self.text_color, font=font_tiny)
            y += 25
        
        y += 10
        draw.line([(40, y), (self.width - 40, y)], fill=(0, 0, 0), width=3)
        y += 30
        
        # Total
        total = data.get('printed_total', 0)
        draw.text((50, y), "TOTAL", fill=self.text_color, font=font_large)
        draw.text((400, y), f"₹{total:.2f}", fill=self.text_color, font=font_large)
        y += 50
        
        # Footer
        draw.text((self.width // 2 - 100, y), "THANK YOU! VISIT AGAIN", fill=(100, 100, 100), font=font_tiny)
        
        return img
    
    def apply_dim_light(self, img):
        """B01: Dim lighting effect with shadow"""
        # Darken the image
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.5)
        
        # Add vignette shadow at bottom
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for i in range(200):
            alpha = int((i / 200) * 120)
            draw.rectangle([(0, img.height - 200 + i), (img.width, img.height - 200 + i + 1)],
                          fill=(0, 0, 0, alpha))
        
        img = img.convert('RGBA')
        img = Image.alpha_composite(img, overlay)
        return img.convert('RGB')
    
    def apply_crumpled(self, img):
        """B02: Crumpled paper effect with creases"""
        # Add stronger noise for texture
        pixels = img.load()
        for i in range(0, img.width, 2):
            for j in range(0, img.height, 2):
                noise = random.randint(-25, 25)
                r, g, b = pixels[i, j]
                pixels[i, j] = (max(0, min(255, r + noise)),
                               max(0, min(255, g + noise)),
                               max(0, min(255, b + noise)))
        
        # Add prominent diagonal crease lines (darker and more visible)
        draw = ImageDraw.Draw(img)
        creases = [
            (50, 150, 550, 500),   # Main diagonal crease
            (80, 80, 520, 650),     # Second crease
            (200, 50, 580, 700),    # Third crease
            (120, 300, 480, 680)    # Fourth crease
        ]
        
        for crease in creases:
            x1, y1, x2, y2 = crease
            # Dark crease shadow
            draw.line([(x1, y1), (x2, y2)], fill=(140, 140, 140), width=4)
            # Lighter highlight on one side
            draw.line([(x1+3, y1+1), (x2+3, y2+1)], fill=(220, 220, 220), width=2)
        
        # Add small wrinkles
        for _ in range(15):
            x = random.randint(50, img.width - 50)
            y = random.randint(50, img.height - 50)
            length = random.randint(30, 80)
            angle = random.uniform(0, 360)
            x2 = x + int(length * math.cos(math.radians(angle)))
            y2 = y + int(length * math.sin(math.radians(angle)))
            draw.line([(x, y), (x2, y2)], fill=(190, 190, 190), width=1)
        
        return img
    
    def apply_steep_angle(self, img):
        """B03: Perspective skew from steep viewing angle"""
        width, height = img.size
        
        # Apply affine transformation (shear + rotation)
        # Simulate viewing from above at an angle
        img = img.transform(
            (width, height),
            Image.AFFINE,
            (1, 0.3, -50, 0.1, 1, -20),  # Shear matrix
            Image.BICUBIC
        )
        
        # Add slight rotation
        img = img.rotate(-8, expand=False, fillcolor=(255, 255, 255))
        
        return img
    
    def apply_faded_thermal(self, img):
        """B04: Faded thermal print effect"""
        # Convert to grayscale first
        img = img.convert('L')
        
        # Lighten (but not too much - should still be readable)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.4)
        
        # Reduce contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(0.5)
        
        # Add subtle faded streaks (less aggressive)
        draw = ImageDraw.Draw(img)
        for y in range(0, img.height, 80):
            alpha_fade = 235 + random.randint(0, 15)
            draw.rectangle([(0, y), (img.width, y + 30)], fill=alpha_fade)
        
        # Add slight blur for thermal paper effect
        img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
        
        return img.convert('RGB')
    
    def apply_handwritten_notes(self, img):
        """B05: Add handwritten tip annotation"""
        draw = ImageDraw.Draw(img)
        
        # Add handwritten-style text (simulated)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except:
            font = ImageFont.load_default()
        
        # Draw a handwritten "tip" note
        y = img.height - 150
        draw.text((80, y), "Tip: ₹150", fill=(0, 0, 200), font=font)
        draw.text((82, y-1), "Tip: ₹150", fill=(0, 0, 200), font=font)  # Double for bold
        
        # Add wavy underline
        for i in range(80, 220, 5):
            draw.line([(i, y+30), (i+5, y+32)], fill=(0, 0, 200), width=2)
        
        return img
    
    def apply_dual_script(self, img):
        """B06: Bilingual Hindi + English"""
        # Add a visual marker/badge indicating bilingual content
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            font = ImageFont.load_default()
        
        # Add bilingual badge at top right
        badge_text = "हिंदी / English"
        draw.rectangle([(img.width - 180, 15), (img.width - 15, 45)], 
                      fill=(255, 200, 100), outline=(200, 150, 50), width=2)
        draw.text((img.width - 165, 20), badge_text, fill=(0, 0, 0), font=font)
        
        return img
    
    def apply_long_receipt(self, img):
        """B07: Extra long receipt (extend height)"""
        # Create taller image
        new_height = int(img.height * 1.4)
        new_img = Image.new('RGB', (img.width, new_height), (255, 255, 255))
        new_img.paste(img, (0, 0))
        
        # Add "continued" marker
        draw = ImageDraw.Draw(new_img)
        try:
            font = ImageFont.truetype("consola.ttf", 20)
        except:
            font = ImageFont.load_default()
        
        y = img.height + 20
        draw.text((img.width // 2 - 80, y), "--- Photo 1 of 2 ---", fill=(100, 100, 100), font=font)
        
        return new_img
    
    def apply_math_error(self, img):
        """B08: Highlight the printed total error"""
        draw = ImageDraw.Draw(img)
        
        # Find total area and add red circle/annotation
        y = img.height - 200
        
        # Draw red circle around total
        draw.ellipse([(380, y-10), (570, y+40)], outline=(255, 0, 0), width=4)
        
        # Add "ERROR" stamp
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except:
            font = ImageFont.load_default()
        
        draw.text((380, y+50), "⚠️ MATH ERROR", fill=(255, 0, 0), font=font)
        
        return img
    
    def apply_heavy_discount(self, img):
        """B09: Promotional discount sticker/stamp"""
        draw = ImageDraw.Draw(img)
        
        # Add "DISCOUNT" stamp
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except:
            font = ImageFont.load_default()
        
        # Rotated discount badge
        stamp = Image.new('RGBA', (250, 100), (255, 0, 0, 0))
        stamp_draw = ImageDraw.Draw(stamp)
        stamp_draw.rectangle([(0, 0), (250, 100)], fill=(220, 20, 20), outline=(180, 0, 0), width=3)
        stamp_draw.text((20, 25), "₹600 OFF!", fill=(255, 255, 255), font=font)
        
        # Rotate and paste
        stamp = stamp.rotate(15, expand=True)
        img.paste(stamp, (200, 150), stamp)
        
        return img
    
    def apply_split_gst(self, img):
        """B10: Clear CGST/SGST breakdown (already in base)"""
        return img
    
    def apply_seven_people(self, img):
        """B11: Add visual marker for complex group bill"""
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except:
            font = ImageFont.load_default()
        
        # Add "Table for 7" marker
        draw.rectangle([(10, 10), (200, 50)], fill=(100, 150, 255), outline=(50, 100, 200), width=2)
        draw.text((30, 20), "TABLE FOR 7", fill=(255, 255, 255), font=font)
        
        return img
    
    def apply_high_density(self, img):
        """B12: Busy cafe with lots of items (already dense in data)"""
        # Add coffee stain effect
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Coffee ring stain
        for r in range(50, 70, 3):
            alpha = 15
            draw.ellipse([(450, 100-r//2), (450+r, 100+r//2)], outline=(139, 69, 19, alpha), width=2)
        
        img = img.convert('RGBA')
        img = Image.alpha_composite(img, overlay)
        return img.convert('RGB')
    
    def generate_bill_image(self, json_path, output_path, condition):
        """Generate a bill image with specific condition applied"""
        print(f"Generating {condition}...")
        
        data = self.load_bill_data(json_path)
        
        # Adjust height based on content
        num_items = len(data.get('items', []))
        base_height = 600 + (num_items * 30)
        self.height = base_height
        
        # Create base receipt
        img = self.create_base_receipt(data)
        
        # Apply condition-specific effects
        if condition == 'dim_light':
            img = self.apply_dim_light(img)
        elif condition == 'crumpled_paper':
            img = self.apply_crumpled(img)
        elif condition == 'steep_angle':
            img = self.apply_steep_angle(img)
        elif condition == 'faded_thermal':
            img = self.apply_faded_thermal(img)
        elif condition == 'handwritten_notes':
            img = self.apply_handwritten_notes(img)
        elif condition == 'dual_script':
            img = self.apply_dual_script(img)
        elif condition == 'multi_photo_stitched':
            img = self.apply_long_receipt(img)
        elif condition == 'math_error_on_bill':
            img = self.apply_math_error(img)
        elif condition == 'promotional_discounts':
            img = self.apply_heavy_discount(img)
        elif condition == 'split_taxes':
            img = self.apply_split_gst(img)
        elif condition == 'seven_people_complex_split':
            img = self.apply_seven_people(img)
        elif condition == 'high_density_items':
            img = self.apply_high_density(img)
        
        # Save
        img.save(output_path, 'JPEG', quality=92)
        print(f"  ✓ Saved to {output_path}")


def main():
    """Generate all 12 bill images"""
    
    dataset_dir = Path('tests/test_dataset')
    images_dir = dataset_dir / 'images'
    images_dir.mkdir(exist_ok=True)
    
    generator = BillImageGenerator()
    
    print("=" * 60)
    print("Generating 12 Synthetic Bill Images")
    print("=" * 60)
    print()
    
    # Generate each bill
    json_files = sorted(dataset_dir.glob('B*.json'))
    
    for json_file in json_files:
        data = json.loads(json_file.read_text(encoding='utf-8'))
        test_id = data.get('test_id', json_file.stem[:3])
        condition = data.get('condition', 'standard')
        
        output_path = images_dir / f"{test_id}.jpg"
        
        generator.generate_bill_image(json_file, output_path, condition)
    
    print()
    print("=" * 60)
    print("✅ All 12 bill images generated successfully!")
    print("=" * 60)
    print()
    print("Location: tests/test_dataset/images/")
    print("Files: B01.jpg through B12.jpg")


if __name__ == "__main__":
    main()
