"""Build the bundled GUI artwork from a local pret/pokefirered checkout."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets"


def build_assets(source: Path) -> None:
    region = source / "graphics" / "region_map"
    tiles_path = region / "region_map.png"
    tilemap_path = region / "kanto.bin"
    sprite_paths = {
        name: source / "graphics" / "pokemon" / name / "front.png"
        for name in ("raikou", "entei", "suicune")
    }
    for path in (tiles_path, tilemap_path, *sprite_paths.values()):
        if not path.is_file():
            raise ValueError(f"No se encontró el recurso requerido: {path.name}")

    tiles = Image.open(tiles_path).convert("RGBA")
    tilemap = tilemap_path.read_bytes()
    if tiles.size != (128, 160) or len(tilemap) != 1200:
        raise ValueError("Los recursos del mapa no tienen el formato esperado")

    map_image = Image.new("RGBA", (240, 160))
    for index in range(600):
        entry = int.from_bytes(tilemap[index * 2 : index * 2 + 2], "little")
        tile_id = entry & 0x3FF
        left = (tile_id % 16) * 8
        top = (tile_id // 16) * 8
        tile = tiles.crop((left, top, left + 8, top + 8))
        if entry & 0x400:
            tile = tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if entry & 0x800:
            tile = tile.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        map_image.paste(tile, ((index % 30) * 8, (index // 30) * 8))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    map_image.save(OUTPUT / "kanto_map.png", optimize=True)
    for name, path in sprite_paths.items():
        Image.open(path).save(OUTPUT / f"{name}.png", optimize=True)

    icon = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle(
        (1, 1, 30, 30),
        radius=7,
        fill="#172640",
        outline="#304260",
        width=2,
    )
    draw.ellipse((6, 6, 25, 25), fill="#e2554d", outline="#fff9e8", width=2)
    draw.line((12, 22, 12, 11, 18, 11, 21, 14, 18, 17, 12, 17), fill="#fff9e8", width=3)
    draw.line((17, 17, 22, 22), fill="#fff9e8", width=3)
    icon.save(OUTPUT / "app_icon.png", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "pokefirered", type=Path, help="Ruta al checkout de pret/pokefirered"
    )
    args = parser.parse_args()
    try:
        build_assets(args.pokefirered)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
