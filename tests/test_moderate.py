import moderate


def _inc(summary, type_="Disturbance", **kw):
    return {"summary": summary, "type": type_, **kw}


# ── model verdict ─────────────────────────────────────────────────────────────

def test_model_no_blocks_with_its_reason():
    inc = _inc("Something", publishable=False, publish_note="describes a suicide attempt")
    assert moderate.block_reason(inc) == "describes a suicide attempt"


def test_model_no_blocks_even_without_a_reason():
    assert moderate.block_reason(_inc("Something", publishable=False)) is not None


def test_model_yes_allows_ordinary_incident():
    inc = _inc("[12:00] Structure Fire — 1 Main St — Engine 3 responded.", "Structure Fire",
               publishable=True)
    assert moderate.block_reason(inc) is None


# ── rule backstop (model gave no verdict) ─────────────────────────────────────

def test_the_post_that_got_flagged_is_blocked():
    """The live post Facebook actioned: no flagged word anywhere in it, which is
    exactly why a stem list could never have caught it."""
    inc = _inc(
        "[18:27] Person in crisis — E. 3rd Street and Rockwell Avenue, Cleveland — A male, "
        "approximately 20 years old, wearing a white t-shirt, was reported attempting to jump "
        "in front of RTA buses. Multiple units responded; EMS was also dispatched to the scene.",
        "Person in crisis",
    )
    assert moderate.block_reason(inc) is not None


def test_rule_catches_explicit_self_harm_wording():
    assert moderate.block_reason(_inc("A caller reported a suicidal male.")) is not None
    assert moderate.block_reason(_inc("The man was threatening to jump from the bridge.")) is not None
    assert moderate.block_reason(_inc("A woman was reported to be a danger to herself.")) is not None


def test_rule_catches_crisis_incident_types():
    assert moderate.block_reason(_inc("Units responded.", "Mental Health Crisis")) is not None
    assert moderate.block_reason(_inc("Units responded.", "Suicide Attempt")) is not None


def test_rule_overrides_a_model_yes():
    """Defence in depth — the model can be wrong about the one category that costs us."""
    inc = _inc("A caller reported a suicidal male.", publishable=True)
    assert moderate.block_reason(inc) is not None


def test_ordinary_incidents_pass_without_any_verdict():
    for summary, type_ in [
        ("[12:00] Structure Fire — 1 Main St — Engine 3 responded.", "Structure Fire"),
        ("[12:00] Two-vehicle crash — Route 82 — No injuries reported.", "Traffic Accident"),
        ("[12:00] Theft — 5 Elm St — A bicycle was reported stolen.", "Theft"),
        ("[12:00] Medical Emergency — 9 Oak Ave — Crews treated a fall victim.", "Medical"),
    ]:
        assert moderate.block_reason(_inc(summary, type_)) is None, summary


def test_shooting_is_not_withheld():
    """Only self-harm is gated by the rule; ordinary crime reporting still posts
    (masked by sanitize), or the model blocks it on graphic detail."""
    inc = _inc("[12:00] Shooting — Lee Road — One person was transported.", "Shooting")
    assert moderate.block_reason(inc) is None


def test_fail_open_env_disables_the_rules(monkeypatch):
    monkeypatch.setattr(moderate, "FAIL_OPEN", True)
    assert moderate.block_reason(_inc("A caller reported a suicidal male.")) is None
    # an explicit model NO still blocks
    assert moderate.block_reason(_inc("x", publishable=False)) is not None
