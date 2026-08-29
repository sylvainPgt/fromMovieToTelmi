#!/usr/bin/env python3
"""Convertit un dossier d'images au format Telmi : JPG 640x480.

Redimensionne et rogne au centre en gardant les proportions
(pas de déformation), puis sauvegarde en JPG.

Exemple :
    python scripts/convert_to_telmi.py mes_images -o telmi_ready
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageOps

TARGET_SIZE = (640, 480)  # Résolution de l'écran de la Telmi
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def convert_image(input_path: Path, output_path: Path, quality: int) -> None:
    with Image.open(input_path) as img:
        # Les modes avec transparence ou palette doivent passer en RGB pour le JPG
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Redimensionne et rogne au centre (center crop) en gardant les proportions
        new_img = ImageOps.fit(
            img, TARGET_SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
        )
        new_img.save(output_path, "JPEG", quality=quality)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "source", type=Path, nargs="?", default=Path("input"),
        help="Dossier contenant les images à convertir (défaut : input)",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("telmi_ready"),
        help="Dossier de sortie (défaut : telmi_ready)",
    )
    parser.add_argument(
        "-q", "--quality", type=int, default=90,
        help="Qualité JPEG de 1 à 100 (défaut : 90)",
    )
    args = parser.parse_args()

    if not args.source.is_dir():
        sys.exit(f"Erreur : dossier introuvable : {args.source}")

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"--- Conversion vers {TARGET_SIZE[0]}x{TARGET_SIZE[1]} ---")

    ok, errors = 0, 0
    for input_path in sorted(args.source.iterdir()):
        if input_path.suffix.lower() not in EXTENSIONS:
            continue
        output_path = args.output / (input_path.stem + ".jpg")
        try:
            convert_image(input_path, output_path, args.quality)
            print(f"✅ OK : {input_path.name}")
            ok += 1
        except Exception as e:
            print(f"❌ Erreur sur {input_path.name} : {e}")
            errors += 1

    suffix = f" ({errors} en erreur)" if errors else ""
    print(f"--- Terminé ! {ok} images converties dans '{args.output}'{suffix} ---")
    if ok == 0 and errors == 0:
        print("Aucune image trouvée dans le dossier source "
              f"(extensions acceptées : {', '.join(sorted(EXTENSIONS))}).")


if __name__ == "__main__":
    main()
