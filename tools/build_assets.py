"""Build the bundled GUI artwork from a local pret/pokefirered checkout."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets"


def build_assets(source: Path) -> None:
    region = source / "graphics" / "region_map"
    pokemon = source / "graphics" / "pokemon" / "suicune"
    tiles_path = region / "region_map.png"
    tilemap_path = region / "kanto.bin"
    suicune_path = pokemon / "front.png"
    icon_path = pokemon / "icon.png"
    for path in (tiles_path, tilemap_path, suicune_path, icon_path):
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
    Image.open(suicune_path).save(OUTPUT / "suicune.png", optimize=True)
    Image.open(icon_path).crop((0, 0, 32, 32)).save(
        OUTPUT / "app_icon.png", optimize=True
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pokefirered", type=Path, help="Ruta al checkout de pret/pokefirered")
    args = parser.parse_args()
    try:
        build_assets(args.pokefirered)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
