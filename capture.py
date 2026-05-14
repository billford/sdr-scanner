"""
Captures a rolling stream from Broadcastify and yields fixed-duration audio chunks
as raw bytes (MP3 frames). Handles reconnects transparently.
"""
import io
import queue
import threading
import time
import logging
from typing import Iterator

import subprocess

import numpy as np

import requests

import dashboard

from config import (
    BROADCASTIFY_FEED_URL,
    CHUNK_DURATION_SECONDS,
    SILENCE_THRESHOLD_RMS,
    STREAM_READ_TIMEOUT,
    STREAM_CHUNK_BYTES,
    ZAPIER_WEBHOOK_URL,
)

log = logging.getLogger(__name__)

# MP3 at 16 kbps mono ≈ 2000 bytes/sec; at 32 kbps ≈ 4000 bytes/sec.
# Broadcastify typically streams 16–32 kbps. We use 4000 bytes/sec as a safe
# upper bound so we don't under-collect a chunk.
BYTES_PER_SECOND = 4000

# Fire the stream-down alarm after this many consecutive failures.
ALARM_FAIL_THRESHOLD = 3


def _send_stream_alarm(url: str, exc: Exception) -> None:
    """Fire a stream-down alarm: macOS notification + Zapier webhook."""
    feed_id = url.rstrip("/").split("/")[-1]
    title = "Scanner Stream Offline"
    msg = f"Feed {feed_id} is down: {exc}"

    # macOS notification (no-op on non-Mac or when running headless)
    try:
        script = f'display notification "{msg}" with title "{title}" sound name "Sosumi"'
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception:  # pylint: disable=broad-exception-caught
        pass

    # Zapier webhook — same endpoint as incidents, differentiated by type field
    if ZAPIER_WEBHOOK_URL:
        try:
            requests.post(
                ZAPIER_WEBHOOK_URL,
                json={"type": "stream_alarm", "summary": f"{title}: feed {feed_id}", "location": None, "time": None},
                timeout=10,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    dashboard.update_stream_status(url, "offline")
    log.error("Stream alarm sent for %s", url)


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
    backoff = 5
    fail_count = 0
    alarm_sent = False

    while True:
        try:
            log.info("Connecting to stream: %s", url)
            with _open_stream(url) as resp:
                if alarm_sent:
                    log.warning("Stream %s reconnected — clearing alarm", url)
                    alarm_sent = False
                dashboard.update_stream_status(url, "online")
                backoff = 5
                fail_count = 0
                for raw in resp.iter_content(chunk_size=STREAM_CHUNK_BYTES):
                    if not raw:
                        continue
                    buf.write(raw)
                    if buf.tell() >= target_bytes:
                        chunk = buf.getvalue()
                        buf = io.BytesIO()
                        yield chunk
        except Exception as exc:  # pylint: disable=broad-exception-caught
            fail_count += 1
            if fail_count <= 3:
                log.warning("Stream error (%s), reconnecting in %ds…", exc, backoff)
            else:
                log.debug("Stream still unavailable (%s), retrying in %ds…", exc, backoff)
            if not alarm_sent and fail_count >= ALARM_FAIL_THRESHOLD:
                _send_stream_alarm(url, exc)
                alarm_sent = True
            # After alarm fires, poll slowly to keep logs quiet
            sleep_for = 600 if alarm_sent else backoff
            time.sleep(sleep_for)
            if not alarm_sent:
                backoff = min(backoff * 2, 300)


def stream_chunks_multi(urls: list[str]) -> Iterator[bytes]:
    """Merges chunks from multiple Broadcastify feeds into one stream."""
    if len(urls) == 1:
        yield from stream_chunks(urls[0])
        return

    q: queue.Queue[bytes] = queue.Queue(maxsize=32)

    def _feed(url: str) -> None:
        for chunk in stream_chunks(url):
            q.put(chunk)

    for url in urls:
        t = threading.Thread(target=_feed, args=(url,), daemon=True)
        t.start()

    while True:
        yield q.get()


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
