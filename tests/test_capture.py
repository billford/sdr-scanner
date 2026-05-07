import os
import struct
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from capture import is_silent, rms_level, stream_chunks


def _make_pcm(frequency=440, sample_rate=8000, duration=0.1, amplitude=10000) -> bytes:
    """Generate a simple sine wave as 16-bit PCM bytes."""
    import math
    n_samples = int(sample_rate * duration)
    samples = [int(amplitude * math.sin(2 * math.pi * frequency * i / sample_rate))
               for i in range(n_samples)]
    return struct.pack(f"<{n_samples}h", *samples)


def _make_silence(n_bytes=8192) -> bytes:
    return bytes(n_bytes)


def _make_noise(n_bytes=8192) -> bytes:
    rng = np.random.default_rng(42)
    return bytes(rng.integers(0, 256, n_bytes, dtype=np.uint8).tolist())


# ── is_silent ─────────────────────────────────────────────────────────────────

def test_is_silent_with_zero_bytes():
    assert is_silent(_make_silence()) is True


def test_is_silent_short_chunk():
    assert is_silent(b"\x80" * 100) is True


def test_is_silent_empty():
    assert is_silent(b"") is True


def test_is_silent_high_entropy_noise():
    assert is_silent(_make_noise()) is False


def test_is_silent_single_repeated_byte():
    # Low variance — all the same byte value
    assert is_silent(bytes([128] * 4096)) is True


# ── rms_level ─────────────────────────────────────────────────────────────────

def test_rms_level_silence():
    assert rms_level(_make_silence()) == 0.0


def test_rms_level_sine_wave():
    pcm = _make_pcm(amplitude=10000)
    rms = rms_level(pcm)
    # RMS of a sine wave ≈ amplitude / sqrt(2) ≈ 7071
    assert 5000 < rms < 9000


def test_rms_level_invalid_data():
    # Odd number of bytes — numpy will truncate, should not raise
    assert rms_level(b"\x01\x02\x03") >= 0.0


# ── stream_chunks ─────────────────────────────────────────────────────────────

def test_stream_chunks_yields_target_size():
    # Generate enough fake bytes to fill two chunks
    from config import CHUNK_DURATION_SECONDS
    target = 4000 * CHUNK_DURATION_SECONDS  # BYTES_PER_SECOND * duration
    fake_data = bytes(target * 2 + 100)

    chunks_data = [fake_data[i:i+4096] for i in range(0, len(fake_data), 4096)]

    mock_resp = MagicMock()
    mock_resp.iter_content.return_value = iter(chunks_data)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("capture.requests.get", return_value=mock_resp):
        gen = stream_chunks("http://fake-url")
        chunk = next(gen)
        assert len(chunk) >= target


def test_stream_chunks_reconnects_on_error():
    call_count = {"n": 0}
    target = 4000 * 60
    fake_data = bytes(target + 100)
    chunks_data = [fake_data[i:i+4096] for i in range(0, len(fake_data), 4096)]

    def mock_get(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("simulated drop")
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = iter(chunks_data)
        return mock_resp

    with patch("capture.requests.get", side_effect=mock_get):
        with patch("capture.time.sleep"):  # don't actually sleep
            gen = stream_chunks("http://fake-url")
            chunk = next(gen)
            assert call_count["n"] == 2  # failed once, reconnected
            assert len(chunk) > 0
