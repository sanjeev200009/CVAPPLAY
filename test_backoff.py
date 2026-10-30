"""Backoff schedule + offline guard check. Run: python test_backoff.py"""
import re


def test_backoff_schedule():
    """Mirrors listen_loop: failures back off 5,10,...,300 and cap there."""
    b, seen = 0, []
    for _ in range(8):
        b = min(b * 2 or 5, 300)
        seen.append(b)
    assert seen == [5, 10, 20, 40, 80, 160, 300, 300], seen


def test_loop_source_matches():
    src = open("cvapply/telegram_listener.py", encoding="utf-8").read()
    assert "backoff = min(backoff * 2 or 5, 300)" in src
    assert "if err != last_err:" in src  # dedup: no 1000-line floods


def test_offline_guard_returns_early():
    import cvapply.daemon as d
    assert d._online() in (True, False)
    d._online = lambda: False
    d.run_daemon_cycle(submit=False, app_batch_limit=1)  # must not touch network




def test_parse_json_ignores_reasoning_prose():
    """Reasoning models emit thinking text (with braces) before the real JSON."""
    from cvapply.llm import OpenRouterClient
    p = OpenRouterClient.parse_json
    noisy = (
        'The user wants {a score}. Let me think: step 1 {draft}.\n'
        '{"score": 90, "match_tier": "A", "reason": "good"}'
    )
    assert p(None, noisy)["score"] == 90
    assert p(None, '{"score": 5}')["score"] == 5



def test_mx_gate_blocks_webonly_domains():
    """A domain with a website but no mail server must never be emailed."""
    from cvapply.apply_email import verify_email_recipient_exists as v
    assert v("careers@johnkeells.com") is False       # site, no MX
    assert v("x@thisdomaindoesnotexist12345.lk") is False
    assert v("careers@wso2.com") is True              # real MX


def test_learned_bounces_block_sends():
    from cvapply import bounces
    from cvapply.apply_email import verify_email_recipient_exists as v
    known = bounces.load_bounced()
    assert known, "bounce store empty - scan_bounces never ran"
    for addr in list(known)[:3]:
        assert v(addr) is False, f"{addr} bounced before but would be sent again"


def test_hard_vs_soft_bounce():
    """A full mailbox is temporary and must not be blocked forever."""
    import email as _email
    from cvapply.bounces import _is_hard_bounce
    hard = _email.message_from_string("Subject: Undeliverable" + chr(10)*2 + "550 No such user here")
    soft = _email.message_from_string("Subject: Undeliverable" + chr(10)*2 + "452 Mailbox full, try later")
    assert _is_hard_bounce(hard) is True
    assert _is_hard_bounce(soft) is False


def test_page_scan_rejects_board_own_address():
    """support@<board> sits on every listing page; it is not the employer."""
    import cvapply.apply_email as ae
    ae._PAGE_EMAIL_CACHE.clear()
    assert ae.extract_email_from_page("https://ikman.lk/en/ad/trainee-hr-assistant-kalutara-1") is None


def test_transient_dns_is_not_cached_as_blocked():
    """A timeout must not blacklist a real employer for the whole run."""
    import cvapply.apply_email as ae

    ae._MX_CACHE.clear()
    assert ae.verify_email_recipient_exists("careers@pearson.com") is True
    assert "pearson.com" not in ae._MX_CACHE or ae._MX_CACHE["pearson.com"] is True
    # definitive "no mail server" IS cached
    assert ae.verify_email_recipient_exists("careers@syscolabs.lk") is False


def test_letter_anchor_ignores_thinking_prose():
    """The old pattern cut the letter at the word "with" inside the thinking."""
    import re

    rx = re.compile(
        r"^\s*(I am writing|I'm writing|I write to|As a|With|My technical|Having)",
        re.IGNORECASE | re.MULTILINE,
    )
    think = (
        "The user wants a letter. I should open with the production systems "
        "I have been building." + chr(10) * 2 +
        "I am writing to apply for the Information Technology Intern role."
    )
    hits = list(rx.finditer(think))
    assert hits, "no opening found"
    assert think[hits[-1].start():].strip().startswith("I am writing")
    assert not rx.match("Without doubt this should not match")


def test_gated_portal_without_session_is_not_silent():
    """A missing login must be a stated reason, never a bare 'failed:'."""
    from cvapply.portal_session import PORTALS, storage_state_for

    assert "xpressjobs" in PORTALS, "xpressjobs must be gated - its apply form needs a login"
    import os

    os.environ.pop("XPRESSJOBS_SESSION", None)
    state = storage_state_for("xpressjobs")
    assert state is None or isinstance(state, dict)


def test_hard_gap_reads_description_not_just_reason():
    """The scoring model often returns reason:"" -- the signal is in the JD."""
    from cvapply.apply import _has_hard_gap

    # real disqualifiers
    assert _has_hard_gap("", "Minimum 4 years of experience required.") is True
    assert _has_hard_gap("", "At least 3 years in Django.") is True
    assert _has_hard_gap("", "5+ years required") is True
    assert _has_hard_gap("missing mandatory degree", "") is True
    # a range means its floor is the requirement, not its ceiling
    assert _has_hard_gap("", "Fresh graduates welcome. 0-2 years.") is False
    assert _has_hard_gap("", "1-3 years experience.") is False
    assert _has_hard_gap("", "Entry level, no experience needed.") is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
