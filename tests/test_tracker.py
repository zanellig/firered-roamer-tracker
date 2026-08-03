from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracker import (  # noqa: E402
    EMERALD,
    EMERALD_ROAMER_ACTIVE_OFFSET,
    EMERALD_ROAMER_ADDR,
    EMERALD_ROAMER_SPECIES_OFFSET,
    EMERALD_SAVE_BLOCK1_PTR_ADDR,
    EMERALD_SAVE_BLOCK2_PTR_ADDR,
    ENTEI,
    FIRERED,
    FIRERED_LEAFGREEN_ROAMER_ACTIVE_OFFSET,
    FIRERED_LEAFGREEN_ROAMER_ADDR,
    FIRERED_LEAFGREEN_ROAMER_SPECIES_OFFSET,
    FIRERED_LEAFGREEN_SAVE_BLOCK1_PTR_ADDR,
    FIRERED_LEAFGREEN_SAVE_BLOCK2_PTR_ADDR,
    FIRERED_LEAFGREEN_STARTER_VAR_OFFSET,
    GAME_TEXT,
    HOENN_MAP_BOUNDS,
    KANTO_MAP_BOUNDS,
    KANTO_ROAMER_ROUTE_GRAPH,
    LATIAS,
    LATIOS,
    LEAFGREEN,
    PLAYER_LOCATION_OFFSET,
    PLAYER_NAME_LENGTH,
    RAIKOU,
    ROM_HEADER_ADDR,
    ROM_HEADER_LENGTH,
    SUICUNE,
    Game,
    RetroArchNCI,
    TrackerError,
    decode_player_name,
    forecast_movement,
    location_for,
    read_snapshot,
)


class FakeReader:
    def __init__(self, values: dict[tuple[int, int], bytes]) -> None:
        self.values = values
        self.reads: list[tuple[int, int]] = []

    def read_memory(self, address: int, length: int) -> bytes:
        self.reads.append((address, length))
        return self.values[(address, length)]


class FakeSocket:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = responses
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.timeout = None
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendto(self, data: bytes, target: tuple[str, int]) -> None:
        self.sent.append((data, target))

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        return self.responses.pop(0), ("127.0.0.1", 55355)

    def close(self) -> None:
        self.closed = True


class LocationTests(unittest.TestCase):
    def test_route_names_and_bounds_share_one_mapping(self) -> None:
        route_1 = location_for(3, 19)
        self.assertEqual(route_1.name, "Ruta 1")
        self.assertEqual(route_1.map_bounds, KANTO_MAP_BOUNDS[19])
        self.assertEqual(route_1.map_bounds.center, (4.0, 9.5))

    def test_non_kanto_area_has_no_map_marker(self) -> None:
        area = location_for(4, 7)
        self.assertEqual(area.name, "Grupo 4 / mapa 7")
        self.assertIsNone(area.map_bounds)

    def test_route_names_account_for_both_route_21_maps(self) -> None:
        self.assertEqual(location_for(3, 39).name, "Ruta 21")
        self.assertEqual(location_for(3, 40).name, "Ruta 21")
        self.assertEqual(location_for(3, 41).name, "Ruta 22")
        self.assertEqual(location_for(3, 44).name, "Ruta 25")

    def test_emerald_route_names_and_bounds_use_the_hoenn_grid(self) -> None:
        route_119 = location_for(0, 34, EMERALD)

        self.assertEqual(route_119.name, "Ruta 119")
        self.assertEqual(route_119.map_bounds, HOENN_MAP_BOUNDS[34])
        self.assertEqual(route_119.map_bounds.center, (11.0, 2.5))


class PlayerNameTests(unittest.TestCase):
    def test_decodes_the_characters_a_trainer_name_can_hold(self) -> None:
        self.assertEqual(decode_player_name(bytes([0xBB, 0xD6, 0xD5, 0xFF])), "Aba")
        self.assertEqual(decode_player_name(bytes([0xBB, 0x00, 0xA2, 0xFF])), "A 1")
        self.assertEqual(decode_player_name(bytes([0xD4, 0xEE, 0xAA])), "Zz9")

    def test_stops_at_the_terminator_and_ignores_the_padding(self) -> None:
        self.assertEqual(
            decode_player_name(bytes([0xBB, 0xBC, 0xFF, 0xBD, 0xBE])), "AB"
        )

    def test_rejects_bytes_that_are_not_a_name(self) -> None:
        for data in (bytes([0xFF]), b"", bytes([0x00, 0x00]), bytes([0xBB, 0x60])):
            with self.subTest(data=data):
                self.assertIsNone(decode_player_name(data))


class MovementForecastTests(unittest.TestCase):
    def test_splits_normal_movement_between_route_neighbors(self) -> None:
        forecast = forecast_movement(
            location_for(3, 34),  # Route 16
            location_for(3, 1),
            location_for(3, 20),
        )

        self.assertIsNotNone(forecast)
        self.assertEqual(
            [chance.location.name for chance in forecast.likely_routes],
            ["Ruta 7", "Ruta 17"],
        )
        for chance in forecast.likely_routes:
            self.assertAlmostEqual(chance.probability, 181 / 384)
        random_only_routes = (
            len(KANTO_ROAMER_ROUTE_GRAPH) - 1 - len(forecast.likely_routes)
        )
        represented_probability = (
            sum(chance.probability for chance in forecast.likely_routes)
            + random_only_routes * forecast.random_route_probability
        )
        self.assertAlmostEqual(represented_probability, 1.0)

    def test_excludes_the_player_map_from_two_transitions_ago(self) -> None:
        forecast = forecast_movement(
            location_for(3, 34),  # Route 16
            location_for(3, 1),
            location_for(3, 25),  # Route 7
        )

        self.assertEqual(len(forecast.likely_routes), 1)
        self.assertEqual(forecast.likely_routes[0].location.name, "Ruta 17")
        self.assertAlmostEqual(forecast.likely_routes[0].probability, 361 / 384)

    def test_recommends_an_immediate_cross_from_a_matching_hunt_city(self) -> None:
        forecast = forecast_movement(
            location_for(3, 23),  # Route 5 can move to Route 6.
            location_for(3, 5),  # Vermilion City
            location_for(3, 19),
        )

        self.assertIsNotNone(forecast.recommendation)
        self.assertEqual(forecast.recommendation.route.name, "Ruta 6")
        self.assertGreater(forecast.recommendation.probability, 0)

    def test_does_not_recommend_a_reset_when_no_direct_cross_exists(self) -> None:
        forecast = forecast_movement(
            location_for(3, 34),
            location_for(3, 7),
            location_for(3, 20),
        )

        self.assertIsNone(forecast.recommendation)

    def test_viridian_interception_accounts_for_the_random_hop(self) -> None:
        forecast = forecast_movement(
            location_for(3, 41),  # Route 22
            location_for(3, 1),  # Viridian City
            location_for(3, 19),  # Entered Viridian from Route 1
        )

        self.assertEqual(
            [chance.location.name for chance in forecast.likely_routes],
            ["Ruta 2", "Ruta 23"],
        )
        for chance in forecast.likely_routes:
            self.assertAlmostEqual(chance.probability, 181 / 384)
        self.assertEqual(forecast.recommendation.route.name, "Ruta 2")
        self.assertAlmostEqual(forecast.recommendation.probability, 181 / 384)

    def test_emerald_uses_its_route_graph_and_random_hop_denominator(self) -> None:
        forecast = forecast_movement(
            location_for(0, 34, EMERALD),  # Route 119
            location_for(0, 4, EMERALD),  # Fortree City
            location_for(0, 25, EMERALD),
            EMERALD,
        )

        self.assertEqual(
            [chance.location.name for chance in forecast.likely_routes],
            ["Ruta 118", "Ruta 120"],
        )
        for chance in forecast.likely_routes:
            self.assertAlmostEqual(chance.probability, 287 / 608)
        self.assertAlmostEqual(forecast.random_route_probability, 1 / 304)
        self.assertEqual(forecast.recommendation.route.name, "Ruta 120")


class SnapshotTests(unittest.TestCase):
    @staticmethod
    def encode_name(name: str) -> bytes:
        byte_for = {character: byte for byte, character in GAME_TEXT.items()}
        return bytes(byte_for[character] for character in name).ljust(
            PLAYER_NAME_LENGTH, b"\xff"
        )

    @staticmethod
    def roamer_state(
        species_id: int,
        active: int,
        species_offset: int,
        active_offset: int,
    ) -> bytes:
        state = bytearray(active_offset - species_offset + 1)
        state[:2] = species_id.to_bytes(2, "little")
        state[-1] = active
        return bytes(state)

    @staticmethod
    def rom_header(game: Game) -> bytes:
        code, revision = {
            FIRERED: (b"BPRE", 1),
            LEAFGREEN: (b"BPGE", 1),
            EMERALD: (b"BPEE", 0),
        }[game]
        return code + bytes(12) + bytes((revision,))

    def values_for(
        self,
        *,
        game: Game = FIRERED,
        save_block: int = 0x02001000,
        save_block2: int = 0x02002000,
        player_name: bytes | None = None,
        species_id: int = SUICUNE.id,
        active: int = 1,
        starter_id: int | None = None,
        roamer_map: tuple[int, int] = (3, 27),
        player_map: tuple[int, int] = (3, 27),
        location_history: tuple[tuple[int, int], ...] = (
            (3, 20),
            (3, 1),
            (3, 20),
        ),
    ) -> dict[tuple[int, int], bytes]:
        if game == EMERALD:
            save_block1_ptr_addr = EMERALD_SAVE_BLOCK1_PTR_ADDR
            save_block2_ptr_addr = EMERALD_SAVE_BLOCK2_PTR_ADDR
            roamer_addr = EMERALD_ROAMER_ADDR
            species_offset = EMERALD_ROAMER_SPECIES_OFFSET
            active_offset = EMERALD_ROAMER_ACTIVE_OFFSET
        else:
            save_block1_ptr_addr = FIRERED_LEAFGREEN_SAVE_BLOCK1_PTR_ADDR
            save_block2_ptr_addr = FIRERED_LEAFGREEN_SAVE_BLOCK2_PTR_ADDR
            roamer_addr = FIRERED_LEAFGREEN_ROAMER_ADDR
            species_offset = FIRERED_LEAFGREEN_ROAMER_SPECIES_OFFSET
            active_offset = FIRERED_LEAFGREEN_ROAMER_ACTIVE_OFFSET
        values = {
            (ROM_HEADER_ADDR, ROM_HEADER_LENGTH): self.rom_header(game),
            (save_block1_ptr_addr, 4): save_block.to_bytes(4, "little"),
            (save_block2_ptr_addr, 4): save_block2.to_bytes(4, "little"),
            (save_block2, PLAYER_NAME_LENGTH): (
                self.encode_name("Gonza") if player_name is None else player_name
            ),
            (save_block + PLAYER_LOCATION_OFFSET, 2): bytes(player_map),
            (
                save_block + species_offset,
                active_offset - species_offset + 1,
            ): self.roamer_state(species_id, active, species_offset, active_offset),
            (roamer_addr - 6, 8): bytes(
                value
                for location in (*location_history, roamer_map)
                for value in location
            ),
        }
        if starter_id is not None:
            values[(save_block + FIRERED_LEAFGREEN_STARTER_VAR_OFFSET, 2)] = (
                starter_id.to_bytes(2, "little")
            )
        return values

    def test_reads_roamer_and_player_and_detects_same_area(self) -> None:
        reader = FakeReader(self.values_for())
        snapshot = read_snapshot(reader)
        self.assertEqual(snapshot.roamer.species, SUICUNE)
        self.assertEqual(snapshot.roamer.location.name, "Ruta 9")
        self.assertTrue(snapshot.roamer.active)
        self.assertEqual(snapshot.player.name, "Ruta 9")
        self.assertTrue(snapshot.same_area)
        self.assertIsNotNone(snapshot.forecast)

    def test_detects_leafgreen_and_reuses_the_kanto_rules(self) -> None:
        snapshot = read_snapshot(FakeReader(self.values_for(game=LEAFGREEN)))

        self.assertEqual(snapshot.game, LEAFGREEN)
        self.assertEqual(snapshot.roamer.species, SUICUNE)
        self.assertEqual(snapshot.roamer.location.name, "Ruta 9")

    def test_reads_both_emerald_roamers_and_hoenn_locations(self) -> None:
        for species in (LATIAS, LATIOS):
            with self.subTest(species=species.name):
                snapshot = read_snapshot(
                    FakeReader(
                        self.values_for(
                            game=EMERALD,
                            species_id=species.id,
                            roamer_map=(0, 34),
                            player_map=(0, 34),
                            location_history=((0, 25), (0, 33), (0, 25)),
                        )
                    )
                )

                self.assertEqual(snapshot.game, EMERALD)
                self.assertEqual(snapshot.roamer.species, species)
                self.assertEqual(snapshot.roamer.location.name, "Ruta 119")
                self.assertTrue(snapshot.same_area)
                self.assertIsNotNone(snapshot.forecast)

    def test_detects_each_roamer_from_the_saved_species(self) -> None:
        for species in (RAIKOU, ENTEI, SUICUNE):
            with self.subTest(species=species.name):
                snapshot = read_snapshot(
                    FakeReader(self.values_for(species_id=species.id))
                )
                self.assertEqual(snapshot.roamer.species, species)

    def test_infers_roamer_from_starter_before_it_is_created(self) -> None:
        expected_by_starter = {
            0: ENTEI,
            1: RAIKOU,
            2: SUICUNE,
        }
        for starter_id, expected in expected_by_starter.items():
            with self.subTest(starter_id=starter_id):
                snapshot = read_snapshot(
                    FakeReader(
                        self.values_for(
                            species_id=0,
                            active=0,
                            starter_id=starter_id,
                        )
                    )
                )
                self.assertEqual(snapshot.roamer.species, expected)
                self.assertFalse(snapshot.roamer.active)

    def test_reads_the_trainer_name_of_every_supported_game(self) -> None:
        for game in (FIRERED, LEAFGREEN, EMERALD):
            with self.subTest(game=game.id):
                snapshot = read_snapshot(
                    FakeReader(
                        self.values_for(
                            game=game,
                            species_id=LATIAS.id if game == EMERALD else SUICUNE.id,
                            player_name=self.encode_name("RED 2"),
                        )
                    )
                )
                self.assertEqual(snapshot.player_name, "RED 2")

    def test_keeps_no_name_when_the_bytes_are_not_one(self) -> None:
        unreadable = {
            "byte outside the character table": self.encode_name("Gonza").replace(
                b"\xd5", b"\x60"
            ),
            "empty name": bytes([0xFF] * PLAYER_NAME_LENGTH),
            "only padding spaces": bytes([0x00] * PLAYER_NAME_LENGTH),
        }
        for reason, name_bytes in unreadable.items():
            with self.subTest(reason=reason):
                snapshot = read_snapshot(
                    FakeReader(self.values_for(player_name=name_bytes))
                )
                self.assertIsNone(snapshot.player_name)

    def test_keeps_no_name_when_the_name_pointer_is_untrusted(self) -> None:
        values = self.values_for()
        values[(FIRERED_LEAFGREEN_SAVE_BLOCK2_PTR_ADDR, 4)] = (0xFFFFFFFF).to_bytes(
            4, "little"
        )

        self.assertIsNone(read_snapshot(FakeReader(values)).player_name)

    def test_same_numbers_in_other_groups_are_not_a_match(self) -> None:
        reader = FakeReader(self.values_for(roamer_map=(4, 27), player_map=(4, 27)))
        self.assertFalse(read_snapshot(reader).same_area)

    def test_reads_game_history_to_exclude_a_likely_route(self) -> None:
        reader = FakeReader(
            self.values_for(
                roamer_map=(3, 34),
                player_map=(3, 1),
                location_history=((3, 1), (3, 25), (3, 20)),
            )
        )

        snapshot = read_snapshot(reader)

        self.assertEqual(
            [chance.location.name for chance in snapshot.forecast.likely_routes],
            ["Ruta 17"],
        )
        self.assertIn((FIRERED_LEAFGREEN_ROAMER_ADDR - 6, 8), reader.reads)

    def test_inactive_roamer_does_not_match_the_player(self) -> None:
        reader = FakeReader(self.values_for(active=0))
        self.assertFalse(read_snapshot(reader).same_area)

    def test_rejects_unknown_roamer_and_starter(self) -> None:
        reader = FakeReader(self.values_for(species_id=999, active=1, starter_id=999))
        with self.assertRaisesRegex(TrackerError, "identificar el roamer"):
            read_snapshot(reader)

    def test_rejects_untrusted_save_block_pointer(self) -> None:
        reader = FakeReader(
            {
                (ROM_HEADER_ADDR, ROM_HEADER_LENGTH): self.rom_header(FIRERED),
                (FIRERED_LEAFGREEN_SAVE_BLOCK1_PTR_ADDR, 4): (0xFFFFFFFF).to_bytes(
                    4, "little"
                ),
            }
        )
        with self.assertRaisesRegex(TrackerError, "bloque de guardado"):
            read_snapshot(reader)

    def test_rejects_an_unsupported_rom_revision_before_reading_ram(self) -> None:
        header = b"BPGE" + bytes(12) + b"\x00"
        reader = FakeReader({(ROM_HEADER_ADDR, ROM_HEADER_LENGTH): header})

        with self.assertRaisesRegex(TrackerError, "versión compatible"):
            read_snapshot(reader)
        self.assertEqual(reader.reads, [(ROM_HEADER_ADDR, ROM_HEADER_LENGTH)])


class ProtocolTests(unittest.TestCase):
    def make_client(self, response: bytes) -> tuple[RetroArchNCI, FakeSocket]:
        fake = FakeSocket([response])
        client = RetroArchNCI(
            "127.0.0.1",
            55355,
            socket_factory=lambda *_args: fake,
        )
        return client, fake

    def test_validates_and_decodes_memory_response(self) -> None:
        # RetroArch's response drops leading zeroes from the requested address.
        client, fake = self.make_client(b"READ_CORE_MEMORY 203f3ae 03 1B\n")
        self.assertEqual(
            client.read_memory(FIRERED_LEAFGREEN_ROAMER_ADDR, 2), bytes((3, 27))
        )
        self.assertEqual(
            fake.sent,
            [(b"READ_CORE_MEMORY 0203F3AE 2", ("127.0.0.1", 55355))],
        )

    def test_rejects_response_for_a_stale_address(self) -> None:
        client, _fake = self.make_client(b"READ_CORE_MEMORY 2000000 03 1B\n")
        with self.assertRaisesRegex(TrackerError, "rechazada"):
            client.read_memory(FIRERED_LEAFGREEN_ROAMER_ADDR, 2)

    def test_rejects_out_of_byte_range_payload(self) -> None:
        client, _fake = self.make_client(b"READ_CORE_MEMORY 0203F3AE 03 100\n")
        with self.assertRaisesRegex(TrackerError, "no es válida"):
            client.read_memory(FIRERED_LEAFGREEN_ROAMER_ADDR, 2)


if __name__ == "__main__":
    unittest.main()
