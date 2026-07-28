"""The user-facing view of the machine.

The coverage test here matters more than it looks. A symptom with no domain is
detected, diagnosed, and then displayed nowhere -- which is worse than not
detecting it, because the work happens and the user never learns of it.
"""

from __future__ import annotations

from warden.contracts import Severity, Symptom
from warden.contracts.state import CollectorHealth
from warden.detectors import build_default_detectors
from warden.domains import BY_ID, DOMAINS, domain_for, summarise, unmapped_symptoms


def healthy(*ids: str) -> dict[str, CollectorHealth]:
    return {i: CollectorHealth(id=i, description="", interval_s=1.0, healthy=True) for i in ids}


def broken(*ids: str) -> dict[str, CollectorHealth]:
    return {i: CollectorHealth(id=i, description="", interval_s=1.0, healthy=False) for i in ids}


def symptom(code: str, severity: Severity = Severity.CRITICAL) -> Symptom:
    return Symptom(code=code, severity=severity, title=f"{code} happened", detector="t")


class TestCoverage:
    def test_every_detectable_symptom_belongs_to_a_domain(self) -> None:
        known = {code for d in build_default_detectors() for code in d.raises}
        assert unmapped_symptoms(known) == set()

    def test_no_domain_claims_a_symptom_nothing_raises(self) -> None:
        known = {code for d in build_default_detectors() for code in d.raises}
        claimed = {code for domain in DOMAINS for code in domain.symptoms}
        assert claimed - known == set(), "a domain lists a symptom no detector can raise"

    def test_every_domain_names_at_least_one_collector(self) -> None:
        for domain in DOMAINS:
            assert domain.collectors, f"{domain.id} has nothing feeding it"

    def test_domains_reference_real_collectors(self) -> None:
        from warden.collectors import build_default_collectors
        from warden.collectors.psbridge import PowerShellBridge

        real = {c.id for c in build_default_collectors(PowerShellBridge())}
        for domain in DOMAINS:
            unknown = set(domain.collectors) - real
            assert not unknown, f"{domain.id} names collectors that do not exist: {unknown}"

    def test_a_symptom_resolves_to_its_domain(self) -> None:
        assert domain_for("CAM.BLOCKED_BY_PRIVACY") is BY_ID["camera"]
        assert domain_for("POWER.BATTERY_WORN") is BY_ID["battery"]
        assert domain_for("NOT.A.REAL.CODE") is None


class TestSummary:
    def test_a_quiet_domain_with_working_collectors_is_ok(self) -> None:
        state, headline = summarise(BY_ID["printing"], [], healthy("sys.services"))
        assert state == "ok"
        assert headline == "Working normally."

    def test_a_critical_symptom_makes_it_a_problem(self) -> None:
        state, headline = summarise(
            BY_ID["printing"], [symptom("PRINT.SPOOLER_STOPPED")], healthy("sys.services")
        )
        assert state == "problem"
        assert "PRINT.SPOOLER_STOPPED happened" in headline

    def test_an_info_symptom_is_only_a_note(self) -> None:
        """The public-network case: worth saying, not worth alarming about."""
        state, _ = summarise(
            BY_ID["sharing"],
            [symptom("NET.PROFILE_PUBLIC_ON_TRUSTED", Severity.INFO)],
            healthy("net.config"),
        )
        assert state == "note"

    def test_the_worst_symptom_decides(self) -> None:
        state, _ = summarise(
            BY_ID["camera"],
            [
                symptom("MIC.BLOCKED_BY_PRIVACY", Severity.WARN),
                symptom("CAM.BLOCKED_BY_PRIVACY", Severity.CRITICAL),
            ],
            healthy("sys.privacy", "sys.services"),
        )
        assert state == "problem"

    def test_a_domain_whose_collectors_all_failed_is_unknown_not_ok(self) -> None:
        """Claiming health because the probe broke is the exact dishonesty this
        project exists to replace."""
        state, headline = summarise(BY_ID["battery"], [], broken("hw.battery"))
        assert state == "unknown"
        assert "cannot say" in headline

    def test_a_domain_with_one_working_collector_is_still_reported(self) -> None:
        state, _ = summarise(
            BY_ID["camera"], [], {**healthy("sys.privacy"), **broken("sys.services")}
        )
        assert state == "ok"

    def test_symptoms_from_other_domains_are_ignored(self) -> None:
        state, _ = summarise(
            BY_ID["printing"], [symptom("AUDIO.SERVICE_STOPPED")], healthy("sys.services")
        )
        assert state == "ok"


class TestPresentation:
    def test_every_domain_reads_as_plain_english(self) -> None:
        """No collector ids, no symptom codes, no jargon in anything user-facing."""
        for domain in DOMAINS:
            assert domain.label[0].isupper()
            assert domain.blurb.endswith("."), f"{domain.id} blurb should be a sentence"
            for text in (domain.label, domain.blurb):
                assert "_" not in text
                assert not any(part in text for part in ("sys.", "net.", "hw.", "cam."))

    def test_domain_ids_are_unique(self) -> None:
        assert len(BY_ID) == len(DOMAINS)
