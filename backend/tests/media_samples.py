"""Smallest byte prefixes the ingestion endpoint recognises as media containers."""

from __future__ import annotations

WEBM = bytes.fromhex("1a45dfa3") + b"\x9fB\x86\x81\x01"  # EBML header
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  "
MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x00"
MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 12
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "
OGG = b"OggS\x00\x02" + b"\x00" * 10
FLAC = b"fLaC\x00\x00\x00\x22" + b"\x00" * 8
