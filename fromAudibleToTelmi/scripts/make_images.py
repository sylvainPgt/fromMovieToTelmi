#!/usr/bin/env python3
"""Fabrique les images des chapitres à partir de la couverture du livre.

Un livre audio n'a qu'une image, sa couverture, souvent carrée. L'écran de
la Telmi est en 640x480 : rogner la couverture couperait son titre. On la
pose donc entière au centre, sur un fond tiré d'elle-même et flouté.

Dans le menu, toutes les images se ressembleraient : chacune reçoit une
pastille avec le numéro du chapitre, pour que l'enfant s'y retrouve.

Exemple :
    python scripts/make_images.py chapitres/chapters.json
    python scripts/make_images.py chapitres/chapters.json --cover ma_couverture.jpg --no-number
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

TARGET_SIZE = (640, 480)
BACKGROUND = (38, 50, 72)
# Polices essayées dans l'ordre : Linux, Windows, macOS. À défaut, celle de Pillow.
FONTS = ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def load_font(size: int) -> ImageFont.ImageFont:
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def cover_canvas(cover: Path | None) -> Image.Image:
    """Couverture entière, centrée sur un fond flouté tiré d'elle-même."""
    if cover is None:
        return Image.new("RGB", TARGET_SIZE, BACKGROUND)
    with Image.open(cover) as source:
        image = source.convert("RGB")
    background = ImageOps.fit(image, TARGET_SIZE, method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(18))
    # Assombrit le fond pour que la couverture ressorte
    background = Image.blend(background, Image.new("RGB", TARGET_SIZE, (0, 0, 0)), 0.35)
    front = ImageOps.contain(image, TARGET_SIZE, method=Image.Resampling.LANCZOS)
    background.paste(front, ((TARGET_SIZE[0] - front.width) // 2,
                             (TARGET_SIZE[1] - front.height) // 2))
    return background


def add_number(image: Image.Image, number: int) -> Image.Image:
    """Ajoute une pastille ronde numérotée en bas à droite."""
    image = image.copy()
    draw = ImageDraw.Draw(image)
    radius = 54
    cx, cy = TARGET_SIZE[0] - radius - 18, TARGET_SIZE[1] - radius - 18
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                 fill=(255, 255, 255), outline=(38, 50, 72), width=6)
    text = str(number)
    font = load_font(64 if number < 10 else 50 if number < 100 else 38)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2), text,
              font=font, fill=(38, 50, 72))
    return image


def make_images(
    chapters: list[dict], folder: Path, cover: Path | None, numbered: bool = True,
) -> list[dict]:
    """Écrit une image par chapitre dans folder. Retourne la liste écrite."""
    folder.mkdir(parents=True, exist_ok=True)
    base = cover_canvas(cover)
    written = []
    for chapter in chapters:
        number = chapter["index"] + 1
        image = add_number(base, number) if numbered else base
        name = chapter.get("image") or f"chapitre_{number:02d}.png"
        image.save(folder / name, "PNG")
        written.append({"index": chapter["index"], "name": name})
    return written


def make_cover(cover: Path | None, destination: Path) -> bool:
    """Image de couverture du pack, sans numéro."""
    if cover is None:
        return False
    cover_canvas(cover).save(destination, "PNG")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifest", type=Path, help="Fichier chapters.json de plan_book.py")
    parser.add_argument("--cover", type=Path, default=None,
                        help="Image de couverture (défaut : celle du livre)")
    parser.add_argument("--no-number", action="store_true",
                        help="Pas de pastille numérotée sur les images")
    args = parser.parse_args()

    if not args.manifest.is_file():
        sys.exit(f"Erreur : fichier introuvable : {args.manifest}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cover = args.cover or (Path(manifest["cover"]) if manifest.get("cover") else None)
    if cover is not None and not cover.is_file():
        sys.exit(f"Erreur : couverture introuvable : {cover}")
    if cover is None:
        print("ℹ️  Pas de couverture : fond uni avec le numéro du chapitre.")

    written = make_images(manifest["chapters"], args.manifest.parent, cover,
                          numbered=not args.no_number)
    if make_cover(cover, args.manifest.parent / "couverture.png"):
        print("Couverture écrite : couverture.png (passez-la à build_pack.py avec --cover)")
    print(f"{len(written)} images écrites dans '{args.manifest.parent}'.")


if __name__ == "__main__":
    main()
