"""The wiring around the cloud model, and four bugs an audit found in it.

None of these were caught by the tests written alongside the feature, because
those tested the pieces and every one of these lives in the joins: a key that is
saved and never loaded, a status object that describes one of two models, a
runner whose output callback was accepted and dropped.
"""

from __future__ import annotations

import inspect

import httpx

from warden import credentials
from warden.contracts import utcnow
from warden.contracts.state import ReasonerHealth
from warden.executor.freeform import FreeformExecutor
from warden.orchestrator.agent import _startup_reasoner_line
from warden.reasoner import Reasoner
from warden.reasoner.cloud import GroqClient, _rate_limited


class TestKeyStorage:
    def test_a_saved_key_can_be_read_back(self, tmp_path, monkeypatch) -> None:
        """The bug: `save_key` wrote to disk and nothing ever called `load_key`
        at startup, so cloud mode switched itself off on every restart while the
        Model page still showed a stored key."""
        monkeypatch.setattr(credentials, "data_path", lambda name: tmp_path / name)
        assert credentials.load_key() is None
        credentials.save_key("gsk_abcdefghijklmnop")
        assert credentials.load_key() == "gsk_abcdefghijklmnop"

    def test_clearing_removes_the_file_rather_than_blanking_it(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(credentials, "data_path", lambda name: tmp_path / name)
        credentials.save_key("gsk_abcdefghijklmnop")
        credentials.clear_key()
        assert credentials.load_key() is None
        assert not (tmp_path / credentials.CREDENTIALS_FILE).exists()

    def test_whitespace_from_a_pasted_key_is_stripped(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(credentials, "data_path", lambda name: tmp_path / name)
        credentials.save_key("  gsk_abcdefghijklmnop\n")
        assert credentials.load_key() == "gsk_abcdefghijklmnop"

    def test_an_unreadable_file_is_treated_as_absent(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(credentials, "data_path", lambda name: tmp_path / name)
        (tmp_path / credentials.CREDENTIALS_FILE).write_text("{ not json", encoding="utf-8")
        assert credentials.load_key() is None

    def test_the_hint_never_reveals_enough_to_use(self) -> None:
        assert credentials.hint("gsk_abcdefghijklmnop") == "...mnop"
        assert credentials.hint(None) == ""
        assert credentials.hint("abc") == "..."


class TestNothingLeaksTheKey:
    def test_the_settings_model_has_nowhere_to_put_one(self) -> None:
        """GET /api/settings serialises this model verbatim, so a key stored in
        it would be handed to the interface on every page load and written into
        every session recording that captured the response."""
        from warden.settings import Settings

        fields = set(Settings.model_fields)
        assert not any("key" in name or "secret" in name or "token" in name for name in fields)

    def test_the_status_model_exposes_a_hint_and_not_a_key(self) -> None:
        from warden.api.app import ReasonerStatus

        fields = set(ReasonerStatus.model_fields)
        assert "cloud_key_hint" in fields
        assert "api_key" not in fields
        assert "cloud_key" not in fields


class TestReasonerHealthDescribesBothBrains:
    def test_it_carries_the_cloud_state_separately(self) -> None:
        """The bug: this described only the local client, so the header pill
        read "rules engine" while a cloud model was answering. That pill is on
        screen at all times and is the product's most repeated promise."""
        health = ReasonerHealth(
            enabled=True,
            available=False,
            model=None,
            endpoint="http://127.0.0.1:11434",
            cloud_enabled=True,
            cloud_available=True,
            cloud_model="llama-3.3-70b-versatile",
        )
        assert health.cloud_available is True
        assert health.cloud_model == "llama-3.3-70b-versatile"

    def test_the_cloud_fields_default_to_off(self) -> None:
        """Every install starts with cloud mode absent, so the defaults have to
        describe that rather than requiring the caller to remember."""
        health = ReasonerHealth(enabled=True, available=True, endpoint="x")
        assert health.cloud_enabled is False
        assert health.cloud_available is False
        assert health.cloud_model is None


class TestCloudCanBeSwitchedWithoutARestart:
    def test_a_reasoner_starts_with_no_cloud(self) -> None:
        assert Reasoner(use_llm=False).cloud is None

    def test_setting_and_clearing_takes_effect_immediately(self) -> None:
        """The key arrives while Warden is already running: the user pastes it
        into the Model page and expects the next diagnosis to use it."""
        reasoner = Reasoner(use_llm=False)
        reasoner.set_cloud(GroqClient(api_key="gsk_test"))
        assert reasoner.cloud is not None
        reasoner.set_cloud(None)
        assert reasoner.cloud is None

    def test_an_unreachable_cloud_client_is_not_available(self) -> None:
        """`available` is false until `refresh_models` has actually reached
        Groq, so a stored-but-dead key degrades to the local model rather than
        raising on every diagnosis."""
        assert GroqClient(api_key="gsk_test").available is False


class TestComposedOutputStreams:
    def test_the_output_callback_is_typed_and_used(self) -> None:
        """The bug: `on_output` was annotated `object | None`, accepted, and
        dropped, because the runner used `subprocess.run` and handed everything
        back at the end. `sfc /scannow` runs for minutes printing progress, and
        a blank panel until it finishes is indistinguishable from a hang."""
        signature = inspect.signature(FreeformExecutor.execute)
        annotation = signature.parameters["on_output"].annotation
        assert "object" not in str(annotation)
        assert "OutputSink" in str(annotation)

    def test_a_refused_command_emits_nothing(self) -> None:
        seen: list[tuple[str, str]] = []
        record = FreeformExecutor().execute(
            ["vssadmin", "delete", "shadows"],
            approved_at=utcnow(),
            on_output=lambda stream, text: seen.append((stream, text)),
        )
        assert record.blocked_reason is not None
        assert seen == [], "a refused command must not reach a process at all"

    def test_output_reaches_the_sink_as_it_arrives(self) -> None:
        """End to end against a real process. `ipconfig` is read-only, fast, on
        every Windows machine, and prints enough to prove the pipes are being
        pumped rather than collected at the end."""
        seen: list[tuple[str, str]] = []
        record = FreeformExecutor().execute(
            ["ipconfig"],
            approved_at=utcnow(),
            reads_only=True,  # no restore point for something that only reads
            on_output=lambda stream, text: seen.append((stream, text)),
        )
        assert record.exit_code == 0
        assert seen, "nothing was streamed"
        assert any(stream == "stdout" for stream, _ in seen)
        assert record.stdout_tail.strip(), "the tail should still be populated"


class TestByteOrderMarks:
    """A BOM is the normal outcome of editing a file on Windows, and it made
    both of Warden's JSON files silently unreadable.

    Notepad writes one. PowerShell 5.1's `Out-File -Encoding utf8` writes one.
    So does a `>` redirection. `json.loads` rejects the three bytes outright, and
    both loaders swallow the error and return defaults -- so a user who opened
    credentials.json to check their key would find cloud mode had quietly
    switched itself off, with nothing on screen explaining why.
    """

    def test_a_key_file_with_a_bom_still_reads(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(credentials, "data_path", lambda name: tmp_path / name)
        (tmp_path / credentials.CREDENTIALS_FILE).write_text(
            '{"groq_api_key": "gsk_abcdefghijklmnop"}', encoding="utf-8-sig"
        )
        assert credentials.load_key() == "gsk_abcdefghijklmnop"

    def test_a_settings_file_with_a_bom_still_reads(self, tmp_path, monkeypatch) -> None:
        from warden import settings

        monkeypatch.setattr(settings, "data_path", lambda name: tmp_path / name)
        (tmp_path / settings.SETTINGS_FILE).write_text(
            '{"theme": "light", "autodiagnose": true, "muted_symptoms": ["TIME.NOT_SYNCHRONISED"]}',
            encoding="utf-8-sig",
        )
        loaded = settings.load()
        assert loaded.theme == "light"
        assert loaded.muted_symptoms == ["TIME.NOT_SYNCHRONISED"]

    def test_a_file_without_a_bom_is_unaffected(self, tmp_path, monkeypatch) -> None:
        """utf-8-sig has to be a no-op on ordinary UTF-8, which is what Warden
        itself writes."""
        monkeypatch.setattr(credentials, "data_path", lambda name: tmp_path / name)
        (tmp_path / credentials.CREDENTIALS_FILE).write_text(
            '{"groq_api_key": "gsk_abcdefghijklmnop"}', encoding="utf-8"
        )
        assert credentials.load_key() == "gsk_abcdefghijklmnop"


class TestStartupSaysWhichBrainItHas:
    """Measured on a live run, and false at the time.

    With a working Groq key, Warden logged "No local model found. Diagnoses will
    use the built-in rules engine." at startup, and then answered the next
    question from the cloud model. The line was written when there was only one
    model to report and never revisited when a second was added.

    A tool whose whole argument is that it does not assert what it has not
    checked cannot announce its own capabilities from a partial check.
    """

    class FakeCloud:
        def __init__(self, available: bool) -> None:
            self.available = available
            self.model = "llama-3.3-70b-versatile"

    def test_cloud_reachable_is_not_reported_as_the_rules_engine(self) -> None:
        text, _ = _startup_reasoner_line(None, self.FakeCloud(True))
        assert "rules engine" not in text
        assert "llama-3.3-70b-versatile" in text

    def test_cloud_reachable_repeats_that_readings_leave_the_machine(self) -> None:
        """The one claim on the box. It is worth saying twice."""
        text, level = _startup_reasoner_line(None, self.FakeCloud(True))
        assert "sent to Groq" in text
        assert level == "warn"

    def test_both_models_are_named_when_both_are_there(self) -> None:
        text, level = _startup_reasoner_line("qwen2.5:1.5b", self.FakeCloud(True))
        assert "llama-3.3-70b-versatile" in text and "qwen2.5:1.5b" in text
        assert level == "info"

    def test_a_key_that_does_not_work_says_so(self) -> None:
        text, level = _startup_reasoner_line(None, self.FakeCloud(False))
        assert "no model answered with that key" in text
        assert level == "warn"

    def test_the_original_message_survives_when_it_is_true(self) -> None:
        text, level = _startup_reasoner_line(None, None)
        assert text == "No local model found. Diagnoses will use the built-in rules engine."
        assert level == "warn"


class TestRateLimitMessagesNameTheRightLimit:
    """Measured, and the first version of this message got it wrong.

    Groq's per-minute headers describe the per-minute bucket, so when the daily
    allowance is spent they read as full and say nothing about the refusal. A
    36-token call succeeded with 11,954 tokens remaining while a 3,000-token one
    was refused with `retry-after: 2136`. Reading the headers therefore produced
    "too frequent", which was false and unactionable.

    The length of the wait is the reliable signal.
    """

    @staticmethod
    def _response(retry_after: str | None, remaining: str = "11954") -> httpx.Response:
        headers = {"x-ratelimit-remaining-tokens": remaining}
        if retry_after is not None:
            headers["retry-after"] = retry_after
        return httpx.Response(429, headers=headers)

    def test_a_long_wait_is_reported_as_the_daily_allowance(self) -> None:
        text = _rate_limited(self._response("2136"))
        assert "daily allowance" in text
        assert "36 minutes" in text
        assert "Nothing is broken" in text

    def test_a_short_wait_is_reported_as_a_per_minute_limit(self) -> None:
        text = _rate_limited(self._response("18"))
        assert "per minute" in text
        assert "18s" in text
        assert "daily" not in text

    def test_no_header_says_so_rather_than_inventing_a_duration(self) -> None:
        text = _rate_limited(self._response(None))
        assert "without saying for how long" in text

    def test_an_unparseable_header_does_not_raise(self) -> None:
        assert _rate_limited(self._response("soon")) != ""
