"""Frame building and stream parsing for the JK BMS BLE protocol."""

from __future__ import annotations

from typing import List

from .constants import CMD_SOR, FRAME_SIZE, HEADER, VALID_TYPES


def crc8(data: bytes) -> int:
    """JK protocol checksum: byte sum truncated to 8 bits."""
    return sum(data) & 0xFF


def build_command(cmd: int, data: bytes = b"") -> bytes:
    """Build the 20-byte JK host command frame (per esphome build_frame)."""
    n = len(data)
    if n > 13:
        raise ValueError("command payload is limited to 13 bytes")
    body = CMD_SOR + bytes([cmd, n]) + data + bytes(13 - n)
    return body + bytes([crc8(body)])


class FrameParser:
    """Incremental parser extracting CRC-valid 300-byte frames from a BLE byte stream."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> List[bytes]:
        """Append a chunk and return every complete, CRC-valid frame found.

        Resynchronises on the 55 AA EB 90 header, so noise between frames or
        partially received frames is discarded safely.
        """
        self._buf.extend(chunk)
        buf = self._buf
        frames: List[bytes] = []
        while True:
            if len(buf) < len(HEADER):
                break
            idx = buf.find(HEADER)
            if idx < 0:
                del buf[: max(0, len(buf) - 3)]
                break
            if idx > 0:
                del buf[:idx]
            if len(buf) < FRAME_SIZE:
                break
            frame = bytes(buf[:FRAME_SIZE])
            if crc8(frame[:-1]) == frame[-1] and frame[4] in VALID_TYPES:
                del buf[:FRAME_SIZE]
                frames.append(frame)
                continue
            nxt = buf.find(HEADER, len(HEADER))
            if nxt < 0:
                del buf[: max(0, len(buf) - 3)]
                break
            del buf[:nxt]
        return frames
