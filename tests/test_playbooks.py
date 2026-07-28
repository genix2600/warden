"""The action registry: grounding guards, rendering, and its own consistency."""

from __future__ import annotations

import pytest

from warden.playbooks import CANDIDATES, PREDICATES, REGISTRY, ActionRejected, render_argv
from warden.store import ObservationStore

from .conftest import make_observation


class TestGrounding:
    """Parameters must be corroborated by something Warden actually observed."""

    def test_a_saved_profile_is_accepted(self, disconnected_store: ObservationStore) -> None:
        proposal = REGISTRY.get("net.wifi.reconnect").propose(
            {"profile": "HomeNet", "interface": "Wi-Fi"}, disconnected_store, rationale="t"
        )
        assert proposal.rendered_argv == [
            "netsh",
            "wlan",
            "connect",
            "name=HomeNet",
            "interface=Wi-Fi",
        ]

    def test_a_network_never_seen_is_refused(self, disconnected_store: ObservationStore) -> None:
        """Schema validation would accept this string. Grounding will not."""
        with pytest.raises(ActionRejected, match="not in this machine's saved"):
            REGISTRY.get("net.wifi.reconnect").propose(
                {"profile": "Free_Airport_WiFi", "interface": "Wi-Fi"},
                disconnected_store,
                rationale="t",
            )

    def test_an_interface_never_seen_is_refused(self, disconnected_store: ObservationStore) -> None:
        with pytest.raises(ActionRejected, match="not a wireless interface"):
            REGISTRY.get("net.adapter.restart").propose(
                {"interface": "Ethernet"}, disconnected_store, rationale="t"
            )

    def test_a_device_not_reporting_a_fault_is_refused(self, store: ObservationStore) -> None:
        store.ingest([make_observation("dev.problem_devices", [])])
        with pytest.raises(ActionRejected, match="no device"):
            REGISTRY.get("dev.driver.restart").propose(
                {"device_id": "PCI\\VEN_8086&DEV_1234", "device_name": "Anything"},
                store,
                rationale="t",
            )

    def test_a_faulted_device_is_accepted(self, store: ObservationStore) -> None:
        store.ingest(
            [
                make_observation(
                    "dev.problem_devices",
                    [{"device_id": "PCI\\VEN_8086&DEV_1234", "problem_code": 43, "name": "GPU"}],
                )
            ]
        )
        proposal = REGISTRY.get("dev.driver.restart").propose(
            {"device_id": "PCI\\VEN_8086&DEV_1234", "device_name": "GPU"}, store, rationale="t"
        )
        assert proposal.rendered_argv[-1] == "PCI\\VEN_8086&DEV_1234"


class TestParameterValidation:
    def test_an_unknown_parameter_is_rejected(self, disconnected_store: ObservationStore) -> None:
        """`extra="forbid"` is what turns an invented field into a refusal."""
        with pytest.raises(ActionRejected, match="invalid"):
            REGISTRY.get("net.wifi.reconnect").propose(
                {"profile": "HomeNet", "interface": "Wi-Fi", "force": True},
                disconnected_store,
                rationale="t",
            )

    @pytest.mark.parametrize(
        "interface",
        ["Wi-Fi'; Remove-Item C:\\ -Recurse", 'Wi-Fi"', "Wi-Fi$(whoami)", "Wi-Fi;calc"],
    )
    def test_shell_metacharacters_cannot_enter_an_interface_name(
        self, disconnected_store: ObservationStore, interface: str
    ) -> None:
        """The one action that interpolates into a PowerShell string is pinned
        to a character class with no quote, dollar or semicolon in it."""
        with pytest.raises(ActionRejected):
            REGISTRY.get("net.adapter.restart").propose(
                {"interface": interface}, disconnected_store, rationale="t"
            )


class TestRendering:
    def test_a_value_with_spaces_stays_one_argument(self) -> None:
        """No shell means no quoting problem: spaces cannot split an argument."""
        argv = render_argv(["netsh", "connect", "name={profile}"], {"profile": "My Home Network"})
        assert argv == ["netsh", "connect", "name=My Home Network"]
        assert len(argv) == 3

    def test_an_unknown_placeholder_is_an_error_not_an_empty_string(self) -> None:
        with pytest.raises(ActionRejected, match="unknown parameter"):
            render_argv(["netsh", "name={missing}"], {"profile": "x"})

    def test_a_token_that_renders_empty_is_refused(self) -> None:
        with pytest.raises(ActionRejected, match="rendered empty"):
            render_argv(["netsh", "{profile}"], {"profile": "   "})


class TestRegistryConsistency:
    def test_every_symptom_a_detector_raises_has_a_decision(self) -> None:
        """Enforced at import; asserted here so the reason is visible on failure."""
        from warden.detectors import build_default_detectors

        detectable = {code for d in build_default_detectors() for code in d.raises}
        assert detectable <= set(CANDIDATES)

    def test_every_referenced_action_exists(self) -> None:
        for actions in CANDIDATES.values():
            for action in actions:
                assert action in REGISTRY

    def test_every_playbook_declares_a_real_verification(self) -> None:
        for playbook in REGISTRY:
            assert playbook.verify.predicate.id in PREDICATES
            assert playbook.verify.predicate.describe.strip()

    def test_no_action_uses_a_shell(self) -> None:
        """The registry is auditable precisely because argv is data, not a string."""
        for playbook in REGISTRY:
            assert isinstance(playbook.argv_template, list)
            assert playbook.argv_template, f"{playbook.id} has an empty command"
            for token in playbook.argv_template:
                assert not token.startswith("cmd"), f"{playbook.id} shells out"

    def test_the_hardware_symptoms_have_no_actions(self) -> None:
        """The routing rule, as data. A physical problem has no command."""
        for code in (
            "THERMAL.SUSTAINED_THROTTLE",
            "THERMAL.HIGH_TEMPERATURE",
            "NET.WIFI.RADIO_OFF",
            "NET.WIFI.NO_ADAPTER",
            "NET.INTERNET.UNREACHABLE",
        ):
            assert CANDIDATES[code] == (), f"{code} acquired a software 'fix'"
