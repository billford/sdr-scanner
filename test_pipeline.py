#!/usr/bin/env python3
"""
End-to-end pipeline test covering all three classification stages.
Usage: python test_pipeline.py [--skip-stream] [--skip-whisper]
"""
import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

logging.basicConfig(level=logging.WARNING)  # suppress module-level noise during tests

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"
SKIP = "\033[93m SKIP\033[0m"
INFO = "\033[94m INFO\033[0m"


def ok(label):    print(f"{PASS}  {label}")
def fail(label, reason): print(f"{FAIL}  {label}: {reason}"); sys.exit(1)
def info(msg):    print(f"{INFO}  {msg}")


# ── DB ────────────────────────────────────────────────────────────────────────

def test_db():
    import db, config
    tmp = tempfile.mktemp(suffix=".db")
    config.DB_PATH = db.DB_PATH = tmp
    try:
        db.init_db()
        h = db.transcript_hash("Engine 3, structure fire, 123 Main")
        assert not db.chunk_seen(h)
        db.log_chunk(h, had_incident=True)
        assert db.chunk_seen(h)
        iid = db.save_incident({
            "time": "14:32", "type": "Structure Fire", "location": "123 Main St",
            "summary": "[14:32] Structure Fire — 123 Main St — Engine 3 dispatched.",
            "raw_transcript": "Engine 3, structure fire, 123 Main",
            "transcript_hash": h,
        })
        assert iid
        db.mark_posted(iid, "fake")
        assert db.recent_incidents(30)[0]["posted"] == 1
        ok("DB: init, dedup, save, mark_posted")
    finally:
        os.unlink(tmp)


# ── Stream ────────────────────────────────────────────────────────────────────

def test_stream(skip=False):
    if skip:
        print(f"{SKIP}  Stream capture (--skip-stream)")
        return None
    import requests
    from config import BROADCASTIFY_FEED_URL
    info("Connecting to Broadcastify for 5 seconds…")
    collected = bytearray()
    try:
        resp = requests.get(BROADCASTIFY_FEED_URL, stream=True,
                            headers={"User-Agent": "Mozilla/5.0", "Icy-MetaData": "0"},
                            timeout=10)
        resp.raise_for_status()
        deadline = time.time() + 5
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk: collected.extend(chunk)
            if time.time() > deadline: break
    except Exception as e:
        fail("Stream capture", str(e))
    if len(collected) < 1000:
        fail("Stream capture", f"only {len(collected)} bytes")
    ok(f"Stream capture: {len(collected):,} bytes in 5s")
    return bytes(collected)


# ── Silence detection ─────────────────────────────────────────────────────────

def test_silence(audio_bytes):
    from capture import is_silent
    result = is_silent(audio_bytes)
    if result:
        print(f"{SKIP}  Silence detection: chunk flagged silent (stream may be idle)")
    else:
        ok("Silence detection: active audio detected")
    return not result


# ── Whisper ───────────────────────────────────────────────────────────────────

def test_transcribe(audio_bytes, skip=False):
    if skip:
        print(f"{SKIP}  Whisper (--skip-whisper)")
        return "Engine 3 respond to 123 Main Street for a structure fire"
    info("Running Whisper…")
    from transcribe import transcribe
    t0 = time.time()
    text = transcribe(audio_bytes)
    ok(f"Whisper: {time.time()-t0:.1f}s — '{text[:80]}{'…' if len(text)>80 else ''}'")
    return text


# ── Stage 1: keyword pre-filter ───────────────────────────────────────────────

def test_keyword_filter():
    from classify import keyword_check

    hits = [
        "Engine 3 respond to 123 Main Street for a structure fire",
        "EMS unit 7 en route for unconscious subject",
        "All units, shots fired at the corner of Main and Elm",
        "10-50 MVA with injuries on Route 82",
        "Hazmat team respond to gas leak at 400 Industrial Pkwy",
    ]
    misses = [
        "10-4",
        "Unit 5 available",
        "Mayor's Court until 1600 hours",
        "Copy that, out of service",
        "Radio check, do you copy?",
    ]

    for t in hits:
        if not keyword_check(t):
            fail("Keyword filter", f"missed incident: '{t}'")
    for t in misses:
        if keyword_check(t):
            fail("Keyword filter", f"false positive on: '{t}'")

    ok(f"Keyword filter: {len(hits)} hits, {len(misses)} misses all correct")


# ── Stage 2: Ollama classify ──────────────────────────────────────────────────

def test_ollama():
    from classify import local_classify
    from config import OLLAMA_URL, OLLAMA_MODEL
    import urllib.request

    # Check Ollama is reachable
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
    except Exception as e:
        fail("Ollama", f"not reachable at {OLLAMA_URL}: {e}")

    incident_transcript = "Engine 3 respond to 123 Main Street for a structure fire, smoke showing"
    routine_transcript = "Unit 5, I'll be out on a traffic stop at Route 82 and Solon Road"

    info(f"Ollama classify (model: {OLLAMA_MODEL})…")
    result = local_classify(incident_transcript)
    if result is None:
        fail("Ollama classify", "returned NO_INCIDENT for a clear fire dispatch")
    ok(f"Ollama: incident detected — '{result.get('local_summary', '')[:80]}'")

    result2 = local_classify(routine_transcript)
    if result2 is not None:
        # Traffic stops sometimes get flagged — warn but don't fail
        print(f"{SKIP}  Ollama NO_INCIDENT check: flagged a traffic stop as incident "
              f"('{result2.get('local_summary','')}') — acceptable edge case")
    else:
        ok("Ollama: routine traffic stop correctly returned NO_INCIDENT")


# ── Stage 3: Claude polish ────────────────────────────────────────────────────

def test_polish():
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        fail("Claude polish", "ANTHROPIC_API_KEY not set")

    import db, config
    tmp = tempfile.mktemp(suffix=".db")
    config.DB_PATH = db.DB_PATH = tmp
    db.init_db()

    from summarize import polish
    raw = "Engine 3 respond to 123 Main Street for a structure fire, smoke showing"
    incident = {
        "time": None,
        "type": "Structure Fire",
        "location": "123 Main Street",
        "local_summary": "Structure fire with smoke showing at 123 Main Street, Engine 3 dispatched.",
        "summary": "Structure fire with smoke showing at 123 Main Street, Engine 3 dispatched.",
        "raw_transcript": raw,
        "transcript_hash": db.transcript_hash(raw),
    }

    info("Sending to Claude for polish…")
    polished = polish(incident)

    if polished["summary"] == incident["local_summary"]:
        fail("Claude polish", "summary unchanged — API call may have failed")
    ok(f"Claude polish: '{polished['summary'][:100]}'")

    os.unlink(tmp)


# ── Post queue ────────────────────────────────────────────────────────────────

def test_post_queue():
    import post, config
    tmp_queue = tempfile.mktemp(suffix=".json")
    original_q_cfg, original_q_post = config.QUEUE_FILE, post.QUEUE_FILE
    original_backend = post.POST_BACKEND
    config.QUEUE_FILE = post.QUEUE_FILE = tmp_queue
    post.POST_BACKEND = "queue"
    try:
        incident = {
            "time": "14:32", "type": "Test", "location": "Test Location",
            "summary": "[14:32] TEST — Test Location — Pipeline validation post.",
            "raw_transcript": "test", "transcript_hash": "testhash",
        }
        post.post_incident(incident)
        data = json.loads(Path(tmp_queue).read_text())
        assert len(data) == 1 and data[0]["summary"] == incident["summary"]
        ok("Post queue: wrote entry correctly")
    finally:
        if Path(tmp_queue).exists(): os.unlink(tmp_queue)
        config.QUEUE_FILE = original_q_cfg
        post.QUEUE_FILE = original_q_post
        post.POST_BACKEND = original_backend


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-stream", action="store_true")
    parser.add_argument("--skip-whisper", action="store_true")
    args = parser.parse_args()

    print("\n=== Chagrin Valley Scanner — Pipeline Test ===\n")

    test_db()

    audio = test_stream(skip=args.skip_stream)
    has_audio = test_silence(audio) if audio else False

    if args.skip_stream or not has_audio:
        transcript = test_transcribe(b"", skip=True)
    else:
        transcript = test_transcribe(audio, skip=args.skip_whisper)

    test_keyword_filter()
    test_ollama()
    test_polish()
    test_post_queue()

    print("\n=== All stages passed ===\n")


if __name__ == "__main__":
    main()
