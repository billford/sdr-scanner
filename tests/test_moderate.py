import moderate


def _inc(summary, type_="Disturbance", **kw):
    return {"summary": summary, "type": type_, **kw}


FLAGGED_POST = (
    "[18:27] Person in crisis — E. 3rd Street and Rockwell Avenue, Cleveland — A male, "
    "approximately 20 years old, wearing a white t-shirt, was reported attempting to jump "
    "in front of RTA buses. Multiple units responded; EMS was also dispatched to the scene."
)


# ── is_crisis ─────────────────────────────────────────────────────────────────

def test_the_post_that_got_flagged_is_recognised():
    """The live post Facebook actioned: no flagged word anywhere in it, which is
    exactly why a stem list could never have caught it."""
    assert moderate.is_crisis(_inc(FLAGGED_POST, "Person in crisis")) is True


def test_model_flag_is_honoured():
    assert moderate.is_crisis(_inc("Officers assisted a person.", "Welfare Check",
                                   crisis=True)) is True


def test_rule_catches_it_even_when_the_model_said_no():
    """A missed one publishes self-harm content with no support line attached."""
    assert moderate.is_crisis(_inc("A caller reported a suicidal male.", crisis=False)) is True


def test_ordinary_incidents_are_not_crisis():
    for summary, type_ in [
        ("[12:00] Structure Fire — 1 Main St — Engine 3 responded.", "Structure Fire"),
        ("[12:00] Two-vehicle crash — Route 82 — No injuries.", "Traffic Accident"),
        ("[12:00] Shooting — Lee Road — One person was transported.", "Shooting"),
        ("[12:00] Medical Emergency — 9 Oak Ave — Crews treated a fall victim.", "Medical"),
    ]:
        assert moderate.is_crisis(_inc(summary, type_)) is False, summary


# ── footer ────────────────────────────────────────────────────────────────────

def test_footer_appended_to_crisis_post():
    out = moderate.apply_footer("[18:27] Welfare Check — Downtown — Officers assisted a person.",
                                _inc("x", "Welfare Check", crisis=True))
    assert "988" in out
    assert out.startswith("[18:27] Welfare Check")


def test_footer_avoids_the_words_that_trip_the_classifier():
    assert "suicide" not in moderate.SUPPORT_FOOTER.lower()
    assert "crisis" not in moderate.SUPPORT_FOOTER.lower()


def test_footer_not_added_to_ordinary_post():
    msg = "[12:00] Structure Fire — 1 Main St — Engine 3 responded."
    assert moderate.apply_footer(msg, _inc(msg, "Structure Fire")) == msg


def test_footer_added_only_once():
    inc = _inc("x", "Welfare Check", crisis=True)
    once = moderate.apply_footer("Officers assisted a person.", inc)
    assert moderate.apply_footer(once, inc) == once


# ── block_reason: withholding is now the rare fallback ────────────────────────

def test_crisis_post_is_published_when_claude_rewrote_it():
    """The whole point of the rewrite: keep the post, don't drop it."""
    inc = _inc("[18:27] Welfare Check — Downtown Cleveland — Officers assisted a person.",
               "Welfare Check", crisis=True)
    assert moderate.block_reason(inc) is None


def test_crisis_withheld_only_when_claude_never_judged_it():
    """No verdict means the summary is the raw local one — written with no
    safe-messaging care, so there is nothing safe to publish."""
    assert moderate.block_reason(_inc(FLAGGED_POST, "Person in crisis")) is not None


def test_explicit_model_no_still_blocks():
    inc = _inc("Something graphic", publishable=False, publish_note="graphic injury detail")
    assert moderate.block_reason(inc) == "graphic injury detail"


def test_ordinary_incident_never_blocked():
    assert moderate.block_reason(_inc("[12:00] Structure Fire — 1 Main St.", "Structure Fire")) is None


def test_fail_open_env_publishes_unjudged_crisis(monkeypatch):
    monkeypatch.setattr(moderate, "FAIL_OPEN", True)
    assert moderate.block_reason(_inc(FLAGGED_POST, "Person in crisis")) is None
    # an explicit model NO still blocks
    assert moderate.block_reason(_inc("x", publishable=False)) is not None
