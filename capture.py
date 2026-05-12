"""
Captures a rolling stream from Broadcastify and yields fixed-duration audio chunks
as raw bytes (MP3 frames). Handles reconnects transparently.
"""
import io
import time
import logging
from typing import Iterator

import numpy as np

import requests

from config import (
    BROADCASTIFY_FEED_URL,
    CHUNK_DURATION_SECONDS,
    SILENCE_THRESHOLD_RMS,
    STREAM_READ_TIMEOUT,
    STREAM_CHUNK_BYTES,
)

log = logging.getLogger(__name__)

# MP3 at 16 kbps mono ≈ 2000 bytes/sec; at 32 kbps ≈ 4000 bytes/sec.
# Broadcastify typically streams 16–32 kbps. We use 4000 bytes/sec as a safe
# upper bound so we don't under-collect a chunk.
BYTES_PER_SECOND = 4000


def _open_stream(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; scanner-monitor/1.0)",
        "Icy-MetaData": "0",
    }
    resp = requests.get(url, stream=True, headers=headers, timeout=STREAM_READ_TIMEOUT)
    resp.raise_for_status()
    return resp


def stream_chunks(url: str = BROADCASTIFY_FEED_URL) -> Iterator[bytes]:
    """Yields one bytes blob per CHUNK_DURATION_SECONDS of captured audio."""
    target_bytes = BYTES_PER_SECOND * CHUNK_DURATION_SECONDS
    buf = io.BytesIO()

    while True:
        try:
            log.info("Connecting to stream: %s", url)
            resp = _open_stream(url)
            for raw in resp.iter_content(chunk_size=STREAM_CHUNK_BYTES):
                if not raw:
                    continue
                buf.write(raw)
                if buf.tell() >= target_bytes:
                    chunk = buf.getvalue()
                    buf = io.BytesIO()
                    yield chunk
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.warning("Stream error (%s), reconnecting in 5s…", exc)
            time.sleep(5)


def rms_level(audio_bytes: bytes) -> float:
    """Rough RMS of raw PCM-16 bytes. Returns 0 on error."""
    try:
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(samples ** 2)))
    except Exception:  # pylint: disable=broad-exception-caught
        return 0.0


def is_silent(chunk: bytes, threshold: int = SILENCE_THRESHOLD_RMS) -> bool:
    """
    Heuristic silence check on a compressed audio chunk.
    We look at the byte-value variance as a proxy; low variance → silence/dead-air.
    A proper implementation would decode to PCM first — this is fast-and-good-enough
    for clear dispatch audio where active speech has high byte entropy.
    """
    if len(chunk) < 512:
        return True
    sample = chunk[: min(len(chunk), 8192)]
    mean = sum(sample) / len(sample)
    variance = sum((b - mean) ** 2 for b in sample) / len(sample)
    # Empirically: silence/noise ≈ variance < 400, speech ≈ variance > 800
    return variance < threshold
