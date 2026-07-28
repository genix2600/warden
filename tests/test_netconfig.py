"""Settings that break things quietly, and the judgement call one of them needs.

Both symptoms exercised here fire on the development machine as it actually is,
with no fault injection: the home network is categorised Public, and the clock
has never reached a time server.
"""

from __future__ import annotations

import pytest

from warden.contracts import ObservationKind, Severity, Verdict
from warden.detectors.netconfig import HostsFileDetector, NetworkProfileDetector, ProxyDetector
from warden.detectors.timesync import TimeSyncDetector
from warden.playbooks import CANDIDATES, REGISTRY, ActionRejected
from warden.playbooks.base import check_template
from warden.playbooks.predicates import PREDICATES
from warden.reasoner.rules import RulesReasoner
from warden.store import ObservationStore

from .conftest import make_observation

INTERNET = 4


def profile(store: ObservationStore, *, category: str, connectivity: int = INTERNET) -> None:
    store.ingest(
        [
            make_observation(
                "net.profile",
                [
                    {
                        "name": "TP-Link_DA45_5G 3",
                        "interface": "Wi-Fi",
                        "category": category,
                        "category_code": {"public": 0, "private": 1, "domain": 2}[category],
                        "ipv4_connectivity": connectivity,
                    }
                ],
            ),
            make_observation("net.wifi.profiles", ["TP-Link_DA45_5G"], ObservationKind.INVENTORY),
        ]
    )


def clock(store: ObservationStore, *, source: str, last_sync: str = "unspecified") -> None:
    store.ingest(
        [
            make_observation(
                "sys.time.sync",
                {
                    "source": source,
                    "leap_indicator": "3(not synchronized)"
                    if source == "Local CMOS Clock"
                    else "0(no warning)",
                    "last_sync": last_sync,
                    "stratum": "0 (unspecified)",
                    "never_synced": last_sync == "unspecified",
                    "free_running": source == "Local CMOS Clock",
                    "not_synchronized": source == "Local CMOS Clock",
                    "phase_offset": None,
                },
            ),
            make_observation(
                "sys.time.peers",
                [{"peer": "time.windows.com,0x9", "state": "Pending"}],
                ObservationKind.INVENTORY,
            ),
        ]
    )


class TestNetworkProfile:
    def test_a_private_network_raises_nothing(self, store: ObservationStore) -> None:
        profile(store, category="private")
        assert NetworkProfileDetector().evaluate(store) == []

    def test_a_public_network_is_reported(self, store: ObservationStore) -> None:
        """Reproduces the development machine's actual state."""
        profile(store, category="public")
        symptoms = NetworkProfileDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["NET.PROFILE_PUBLIC_ON_TRUSTED"]

    def test_it_is_reported_as_information_not_a_fault(self, store: ObservationStore) -> None:
        """Public is the *safe* default. Presenting it as a critical fault would
        push users into a security regression on cafe and airport networks."""
        profile(store, category="public")
        symptom = NetworkProfileDetector().evaluate(store)[0]
        assert symptom.severity is Severity.INFO
        assert symptom.facts["is_a_choice_not_a_fault"] is True
        assert "trust" in symptom.facts["security_tradeoff"]

    def test_it_stays_quiet_on_a_network_that_is_not_working(self, store: ObservationStore) -> None:
        """Never pile a note about sharing on top of a connection that is down."""
        profile(store, category="public", connectivity=0)
        assert NetworkProfileDetector().evaluate(store) == []

    def test_the_diagnosis_presents_both_sides(self, store: ObservationStore) -> None:
        profile(store, category="public")
        symptom = NetworkProfileDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)
        assert diagnosis.verdict is Verdict.ACTIONABLE
        assert "cafe" in diagnosis.summary
        assert diagnosis.proposal is not None
        # The exposure is stated on the card the user approves, not buried.
        assert "do not trust" in diagnosis.proposal.expected_effect

    def test_an_already_private_network_cannot_be_changed(self, store: ObservationStore) -> None:
        profile(store, category="private")
        with pytest.raises(ActionRejected, match="already private"):
            REGISTRY.get("net.profile.private").propose(
                {"name": "TP-Link_DA45_5G 3"}, store, rationale="t"
            )

    def test_an_unseen_network_cannot_be_changed(self, store: ObservationStore) -> None:
        profile(store, category="public")
        with pytest.raises(ActionRejected, match="not a network Warden can currently see"):
            REGISTRY.get("net.profile.private").propose(
                {"name": "Someone Elses WiFi"}, store, rationale="t"
            )


class TestClock:
    def test_a_synchronised_clock_raises_nothing(self, store: ObservationStore) -> None:
        clock(store, source="time.windows.com", last_sync="28/07/2026 18:00:00")
        assert TimeSyncDetector().evaluate(store) == []

    def test_a_free_running_clock_is_reported(self, store: ObservationStore) -> None:
        """Reproduces the development machine: never synced, on the CMOS clock."""
        clock(store, source="Local CMOS Clock")
        symptoms = TimeSyncDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["TIME.NOT_SYNCHRONISED"]
        assert symptoms[0].facts["never_synced"] is True
        assert symptoms[0].facts["pending_peers"] == ["time.windows.com,0x9"]

    def test_the_explanation_leads_with_the_consequence(self, store: ObservationStore) -> None:
        """Nobody reports an unsynchronised clock. They report broken websites."""
        clock(store, source="Local CMOS Clock")
        symptom = TimeSyncDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)
        assert "secure websites stop loading" in diagnosis.summary
        assert diagnosis.proposal is not None
        assert diagnosis.proposal.action_id == "time.resync"

    def test_the_check_reads_the_clock_source_back(self, store: ObservationStore) -> None:
        predicate = PREDICATES["time.synchronised"]
        clock(store, source="Local CMOS Clock")
        assert predicate(store, {})[0] is False
        clock(store, source="time.windows.com", last_sync="28/07/2026 18:00:00")
        assert predicate(store, {})[0] is True


class TestProxy:
    def _proxy(self, store: ObservationStore, *, enabled: bool, reachable: bool) -> None:
        store.ingest(
            [
                make_observation(
                    "net.proxy",
                    {
                        "winhttp_direct": not enabled,
                        "winhttp_server": "10.0.0.9:8080" if enabled else None,
                        "user_proxy_enabled": enabled,
                        "user_proxy_server": "10.0.0.9:8080" if enabled else None,
                        "auto_config_url": None,
                    },
                ),
                make_observation("net.connectivity.internet", reachable),
            ]
        )

    def test_no_proxy_raises_nothing(self, store: ObservationStore) -> None:
        self._proxy(store, enabled=False, reachable=True)
        assert ProxyDetector().evaluate(store) == []

    def test_a_working_proxy_raises_nothing(self, store: ObservationStore) -> None:
        """Plenty of corporate machines use one perfectly happily."""
        self._proxy(store, enabled=True, reachable=True)
        assert ProxyDetector().evaluate(store) == []

    def test_a_proxy_with_no_connectivity_is_the_finding(self, store: ObservationStore) -> None:
        self._proxy(store, enabled=True, reachable=False)
        symptoms = ProxyDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["NET.PROXY_CONFIGURED_BUT_OFFLINE"]
        assert symptoms[0].facts["proxy_server"] == "10.0.0.9:8080"


class TestHostsFile:
    def test_a_clean_hosts_file_raises_nothing(self, store: ObservationStore) -> None:
        store.ingest([make_observation("net.hosts", [], ObservationKind.INVENTORY)])
        assert HostsFileDetector().evaluate(store) == []

    def test_localhost_lines_are_not_findings(self, store: ObservationStore) -> None:
        store.ingest(
            [
                make_observation(
                    "net.hosts",
                    [
                        {
                            "line": 1,
                            "address": "127.0.0.1",
                            "hosts": ["localhost"],
                            "blackholed": True,
                        }
                    ],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        assert HostsFileDetector().evaluate(store) == []

    def test_a_redirected_site_is_reported_but_not_assumed_malicious(
        self, store: ObservationStore
    ) -> None:
        store.ingest(
            [
                make_observation(
                    "net.hosts",
                    [
                        {
                            "line": 5,
                            "address": "0.0.0.0",
                            "hosts": ["ads.example.com"],
                            "blackholed": True,
                            "text": "0.0.0.0 ads.example.com",
                        }
                    ],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        symptom = HostsFileDetector().evaluate(store)[0]
        assert symptom.code == "NET.HOSTS_OVERRIDE"
        assert symptom.facts["may_be_deliberate"] is True

    def test_choosing_which_entry_to_disable_is_left_to_the_user(
        self, store: ObservationStore
    ) -> None:
        """Ad blockers write these deliberately, so Warden will not pick for you."""
        store.ingest(
            [
                make_observation(
                    "net.hosts",
                    [{"line": 5, "address": "0.0.0.0", "hosts": ["ads.example.com"]}],
                    ObservationKind.INVENTORY,
                )
            ]
        )
        symptom = HostsFileDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)
        assert diagnosis.verdict is Verdict.NEEDS_MORE_DATA
        assert diagnosis.proposal is None


class TestTemplateSafety:
    """The check that caught two real bugs the moment it was added."""

    def test_every_registered_template_is_a_valid_format_string(self) -> None:
        for playbook in REGISTRY:
            check_template(playbook)

    def test_a_literal_powershell_brace_is_rejected(self) -> None:
        """This is the exact shape of the bug that shipped twice."""
        from warden.contracts import PredicateRef, RiskTier, VerifySpec
        from warden.playbooks.base import NoParams, Playbook

        broken = Playbook(
            id="test.broken",
            title="t",
            summary="t",
            when_to_use="t",
            risk=RiskTier.READ_ONLY,
            params_model=NoParams,
            # A PowerShell script block. Single braces make this a format
            # string whose "parameter" is " $_.Name ", which no model defines.
            argv_template=["powershell", "-Command", "Get-Thing | ForEach-Object { $_.Name }"],
            expected_effect="t",
            verify=VerifySpec(probes=[], predicate=PredicateRef(id="report.only", describe="t")),
        )
        with pytest.raises(ValueError, match="does not define"):
            check_template(broken)

    def test_nested_literal_braces_are_rejected_with_a_usable_message(self) -> None:
        """The exact shape that shipped: an if-block inside a ForEach-Object."""
        from warden.contracts import PredicateRef, RiskTier, VerifySpec
        from warden.playbooks.base import NoParams, Playbook

        broken = Playbook(
            id="test.nested",
            title="t",
            summary="t",
            when_to_use="t",
            risk=RiskTier.READ_ONLY,
            params_model=NoParams,
            argv_template=["powershell", "-Command", "x | ForEach-Object { if ($_) { $_ } }"],
            expected_effect="t",
            verify=VerifySpec(probes=[], predicate=PredicateRef(id="report.only", describe="t")),
        )
        with pytest.raises(ValueError, match="literal brace"):
            check_template(broken)

    def test_a_placeholder_the_model_does_not_define_is_rejected(self) -> None:
        from warden.contracts import PredicateRef, RiskTier, VerifySpec
        from warden.playbooks.base import NoParams, Playbook

        broken = Playbook(
            id="test.unknown",
            title="t",
            summary="t",
            when_to_use="t",
            risk=RiskTier.READ_ONLY,
            params_model=NoParams,
            argv_template=["netsh", "connect", "name={ssid}"],
            expected_effect="t",
            verify=VerifySpec(probes=[], predicate=PredicateRef(id="report.only", describe="t")),
        )
        with pytest.raises(ValueError, match="does not define"):
            check_template(broken)

    def test_the_temp_report_template_renders(self, store: ObservationStore) -> None:
        """Regression: this action was silently un-proposable until the check found it."""
        proposal = REGISTRY.get("sys.disk.temp_report").propose({}, store, rationale="t")
        assert "ForEach" in proposal.rendered_argv[-1] or "foreach" in proposal.rendered_argv[-1]
        assert "{0}" in proposal.rendered_argv[-1]


class TestRegistration:
    @pytest.mark.parametrize(
        ("code", "action"),
        [
            ("NET.PROFILE_PUBLIC_ON_TRUSTED", "net.profile.private"),
            ("NET.PROXY_CONFIGURED_BUT_OFFLINE", "net.proxy.reset"),
            ("NET.HOSTS_OVERRIDE", "net.hosts.comment"),
            ("TIME.NOT_SYNCHRONISED", "time.resync"),
        ],
    )
    def test_each_symptom_maps_to_its_action(self, code: str, action: str) -> None:
        assert CANDIDATES[code] == (action,)
        assert REGISTRY.get(action).verify.predicate.id in PREDICATES
