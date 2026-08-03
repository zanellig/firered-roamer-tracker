"""Build bundled artwork from local pret FRLG and Emerald checkouts."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets"


def _tile(tiles: Image.Image, tile_id: int) -> Image.Image:
    tiles_per_row = tiles.width // 8
    left = (tile_id % tiles_per_row) * 8
    top = (tile_id // tiles_per_row) * 8
    return tiles.crop((left, top, left + 8, top + 8))


def _build_kanto_map(source: Path) -> Image.Image:
    region = source / "graphics" / "region_map"
    tiles_path = region / "region_map.png"
    tilemap_path = region / "kanto.bin"
    for path in (tiles_path, tilemap_path):
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
        tile = _tile(tiles, tile_id)
        if entry & 0x400:
            tile = tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if entry & 0x800:
            tile = tile.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        map_image.paste(tile, ((index % 30) * 8, (index // 30) * 8))
    return map_image


def _build_hoenn_map(source: Path) -> Image.Image:
    region = source / "graphics" / "pokenav" / "region_map"
    tiles_path = region / "map.png"
    tilemap_path = region / "map.bin"
    for path in (tiles_path, tilemap_path):
        if not path.is_file():
            raise ValueError(f"No se encontró el recurso requerido: {path.name}")

    tiles = Image.open(tiles_path).convert("RGBA")
    tilemap = tilemap_path.read_bytes()
    if tiles.size != (128, 120) or len(tilemap) != 4096:
        raise ValueError("Los recursos del mapa de Hoenn no tienen el formato esperado")

    # Emerald uses an affine 64-by-64 byte tilemap. Its visible GBA screen is
    # the first 30 by 20 tiles, including the same margins shown in-game.
    map_image = Image.new("RGBA", (240, 160))
    for y in range(20):
        for x in range(30):
            tile_id = tilemap[y * 64 + x]
            map_image.paste(_tile(tiles, tile_id), (x * 8, y * 8))
    return map_image


def build_assets(pokefirered: Path, pokeemerald: Path) -> None:
    sprite_paths = {
        **{
            name: pokefirered / "graphics" / "pokemon" / name / "front.png"
            for name in ("raikou", "entei", "suicune")
        },
        **{
            name: pokeemerald / "graphics" / "pokemon" / name / "front.png"
            for name in ("latias", "latios")
        },
    }
    for path in sprite_paths.values():
        if not path.is_file():
            raise ValueError(f"No se encontró el recurso requerido: {path.name}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    _build_kanto_map(pokefirered).save(OUTPUT / "kanto_map.png", optimize=True)
    _build_hoenn_map(pokeemerald).save(OUTPUT / "hoenn_map.png", optimize=True)
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
    parser.add_argument(
        "pokeemerald", type=Path, help="Ruta al checkout de pret/pokeemerald"
    )
    args = parser.parse_args()
    try:
        build_assets(args.pokefirered, args.pokeemerald)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
