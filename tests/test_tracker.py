from __future__ import annotations

import socket
import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker import (  # noqa: E402
    KANTO_MAP_BOUNDS,
    ROAMER_ADDR,
    SAVE_BLOCK1_PTR_ADDR,
    RetroArchNCI,
    TrackerError,
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


class SnapshotTests(unittest.TestCase):
    def test_reads_roamer_and_player_and_detects_same_area(self) -> None:
        save_block = 0x02001000
        reader = FakeReader(
            {
                (ROAMER_ADDR, 2): bytes((3, 27)),
                (SAVE_BLOCK1_PTR_ADDR, 4): save_block.to_bytes(4, "little"),
                (save_block + 4, 2): bytes((3, 27)),
            }
        )
        snapshot = read_snapshot(reader)
        self.assertEqual(snapshot.suicune.name, "Ruta 9")
        self.assertEqual(snapshot.player.name, "Ruta 9")
        self.assertTrue(snapshot.same_area)

    def test_same_numbers_in_other_groups_are_not_a_match(self) -> None:
        save_block = 0x02001000
        reader = FakeReader(
            {
                (ROAMER_ADDR, 2): bytes((4, 27)),
                (SAVE_BLOCK1_PTR_ADDR, 4): save_block.to_bytes(4, "little"),
                (save_block + 4, 2): bytes((4, 27)),
            }
        )
        self.assertFalse(read_snapshot(reader).same_area)

    def test_rejects_untrusted_save_block_pointer(self) -> None:
        reader = FakeReader(
            {
                (ROAMER_ADDR, 2): bytes((3, 27)),
                (SAVE_BLOCK1_PTR_ADDR, 4): (0xFFFFFFFF).to_bytes(4, "little"),
            }
        )
        with self.assertRaisesRegex(TrackerError, "bloque de guardado"):
            read_snapshot(reader)


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
        self.assertEqual(client.read_memory(ROAMER_ADDR, 2), bytes((3, 27)))
        self.assertEqual(
            fake.sent,
            [(b"READ_CORE_MEMORY 0203F3AE 2", ("127.0.0.1", 55355))],
        )

    def test_rejects_response_for_a_stale_address(self) -> None:
        client, _fake = self.make_client(b"READ_CORE_MEMORY 2000000 03 1B\n")
        with self.assertRaisesRegex(TrackerError, "rechazada"):
            client.read_memory(ROAMER_ADDR, 2)

    def test_rejects_out_of_byte_range_payload(self) -> None:
        client, _fake = self.make_client(b"READ_CORE_MEMORY 0203F3AE 03 100\n")
        with self.assertRaisesRegex(TrackerError, "no es válida"):
            client.read_memory(ROAMER_ADDR, 2)


if __name__ == "__main__":
    unittest.main()
