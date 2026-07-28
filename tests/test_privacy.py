"""Camera and microphone: the invisible-cause domain.

A denied capability produces a black image or silence with no error message.
Users reinstall drivers and eventually conclude the hardware failed, for a
setting one value change away. These tests pin the three distinct causes apart,
and pin the registry path so it cannot drift.
"""

from __future__ import annotations

import pytest

from warden.contracts import ObservationKind, Severity, Verdict
from warden.detectors.privacy import CameraDeviceDetector, PrivacyBlockDetector
from warden.playbooks import CANDIDATES, REGISTRY, ActionRejected
from warden.playbooks.predicates import PREDICATES
from warden.playbooks.privacy import PrivacyParams, consent_key
from warden.reasoner.rules import RulesReasoner
from warden.store import ObservationStore

from .conftest import make_observation

CONSENT_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


def consent(store: ObservationStore, label: str, *, user: str, machine: str = "Allow") -> None:
    store.ingest(
        [
            make_observation(
                f"privacy.{label}",
                {
                    "capability": "webcam" if label == "camera" else "microphone",
                    "user": user,
                    "machine": machine,
                    "denied_apps": [],
                    "app_count": 9,
                },
            )
        ]
    )


def cameras(store: ObservationStore, *, status: str = "OK", problem: int | None = 0) -> None:
    store.ingest(
        [
            make_observation(
                "cam.devices",
                [
                    {
                        "name": "HP Wide Vision HD Camera",
                        "status": status,
                        "instance_id": r"USB\VID_05C8&PID_03DF&MI_00\6&4BB6AA2&0&0000",
                        "problem_code": problem,
                    }
                ],
                ObservationKind.INVENTORY,
            )
        ]
    )


class TestConsent:
    def test_allowed_raises_nothing(self, store: ObservationStore) -> None:
        consent(store, "camera", user="Allow")
        consent(store, "microphone", user="Allow")
        assert PrivacyBlockDetector().evaluate(store) == []

    def test_an_absent_value_is_not_a_denial(self, store: ObservationStore) -> None:
        """Windows treats a missing consent key as allowed.

        Inventing a denial because a key does not exist would raise a critical
        fault on a clean install.
        """
        store.ingest(
            [
                make_observation(
                    "privacy.camera",
                    {"capability": "webcam", "user": None, "machine": None, "denied_apps": []},
                )
            ]
        )
        assert PrivacyBlockDetector().evaluate(store) == []

    def test_a_user_denial_is_reported(self, store: ObservationStore) -> None:
        consent(store, "camera", user="Deny")
        symptoms = PrivacyBlockDetector().evaluate(store)
        assert [s.code for s in symptoms] == ["CAM.BLOCKED_BY_PRIVACY"]
        assert symptoms[0].severity is Severity.CRITICAL
        assert symptoms[0].facts["blocked_scope"] == "user"

    def test_a_machine_denial_wins_over_the_user_setting(self, store: ObservationStore) -> None:
        """The case that makes people give up: they allowed it, and it stayed broken."""
        consent(store, "camera", user="Allow", machine="Deny")
        symptom = PrivacyBlockDetector().evaluate(store)[0]
        assert symptom.facts["blocked_scope"] == "machine"
        assert "whole machine" in symptom.detail

    def test_the_microphone_is_covered_too(self, store: ObservationStore) -> None:
        consent(store, "microphone", user="Deny")
        assert [s.code for s in PrivacyBlockDetector().evaluate(store)] == [
            "MIC.BLOCKED_BY_PRIVACY"
        ]

    def test_both_can_be_blocked_at_once(self, store: ObservationStore) -> None:
        consent(store, "camera", user="Deny")
        consent(store, "microphone", user="Deny")
        assert sorted(s.code for s in PrivacyBlockDetector().evaluate(store)) == [
            "CAM.BLOCKED_BY_PRIVACY",
            "MIC.BLOCKED_BY_PRIVACY",
        ]


class TestCameraDevice:
    def test_a_working_camera_raises_nothing(self, store: ObservationStore) -> None:
        cameras(store)
        assert CameraDeviceDetector().evaluate(store) == []

    def test_no_camera_is_not_a_fault(self, store: ObservationStore) -> None:
        """Most desktops have none, and that is not something to report."""
        store.ingest([make_observation("cam.devices", [], ObservationKind.INVENTORY)])
        assert CameraDeviceDetector().evaluate(store) == []

    def test_a_deliberately_disabled_camera_is_distinguished(self, store: ObservationStore) -> None:
        cameras(store, status="Error", problem=22)
        symptom = CameraDeviceDetector().evaluate(store)[0]
        assert symptom.code == "CAM.DEVICE_DISABLED"
        assert symptom.facts["deliberately_disabled"] is True
        assert "switched off" in symptom.title

    def test_a_failed_camera_is_not_called_disabled(self, store: ObservationStore) -> None:
        cameras(store, status="Error", problem=10)
        symptom = CameraDeviceDetector().evaluate(store)[0]
        assert symptom.facts["deliberately_disabled"] is False
        assert "not working" in symptom.title


class TestRegistrySafety:
    def test_the_path_is_built_from_enums_not_supplied(self) -> None:
        assert consent_key("webcam", "user") == f"HKCU:\\{CONSENT_PATH}\\webcam"
        assert consent_key("microphone", "machine") == f"HKLM:\\{CONSENT_PATH}\\microphone"

    def test_the_hive_is_derived_not_accepted(self) -> None:
        """`scope_hive` is computed, so no caller can supply a hive."""
        params = PrivacyParams(capability="webcam", scope="machine")
        assert params.scope_hive == "HKLM:"
        with pytest.raises(ValueError):
            PrivacyParams(capability="webcam", scope="machine", scope_hive="HKCR:")  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "bad",
        [
            {"capability": "webcam", "scope": "HKLM:\\SOFTWARE\\Anything"},
            {"capability": "..\\..\\Run", "scope": "user"},
            {"capability": "webcam", "scope": "system"},
        ],
    )
    def test_a_path_cannot_be_smuggled_through_a_parameter(
        self, store: ObservationStore, bad: dict
    ) -> None:
        consent(store, "camera", user="Deny")
        with pytest.raises(ActionRejected):
            REGISTRY.get("privacy.allow").propose(bad, store, rationale="t")

    def test_the_rendered_command_targets_the_expected_key(self, store: ObservationStore) -> None:
        consent(store, "camera", user="Deny")
        proposal = REGISTRY.get("privacy.allow").propose(
            {"capability": "webcam", "scope": "user"}, store, rationale="t"
        )
        assert proposal.rendered_argv[-1] == (
            f"Set-ItemProperty -Path 'HKCU:\\{CONSENT_PATH}\\webcam' "
            "-Name Value -Value Allow -ErrorAction Stop"
        )

    def test_nothing_is_changed_when_nothing_is_denied(self, store: ObservationStore) -> None:
        consent(store, "camera", user="Allow")
        with pytest.raises(ActionRejected, match="nothing to change"):
            REGISTRY.get("privacy.allow").propose(
                {"capability": "webcam", "scope": "user"}, store, rationale="t"
            )

    def test_an_unknown_camera_cannot_be_enabled(self, store: ObservationStore) -> None:
        cameras(store, status="Error", problem=22)
        with pytest.raises(ActionRejected, match="not among the cameras"):
            REGISTRY.get("cam.device.enable").propose(
                {"instance_id": r"USB\SOMETHING_ELSE", "device_name": "Fake"},
                store,
                rationale="t",
            )


class TestRouting:
    def test_a_blocked_camera_proposes_the_setting_not_the_device(
        self, store: ObservationStore
    ) -> None:
        """Permission first: touching the device would not help and is riskier."""
        consent(store, "camera", user="Deny")
        cameras(store)
        symptom = PrivacyBlockDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)

        assert diagnosis.verdict is Verdict.ACTIONABLE
        assert diagnosis.proposal is not None
        assert diagnosis.proposal.action_id == "privacy.allow"
        assert "hardware is fine" in diagnosis.summary

    def test_the_machine_scope_explanation_names_why_settings_did_not_help(
        self, store: ObservationStore
    ) -> None:
        consent(store, "camera", user="Allow", machine="Deny")
        symptom = PrivacyBlockDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)
        assert "your own Settings did not help" in diagnosis.summary

    def test_a_disabled_camera_proposes_enabling_the_device(self, store: ObservationStore) -> None:
        cameras(store, status="Error", problem=22)
        symptom = CameraDeviceDetector().evaluate(store)[0]
        diagnosis = RulesReasoner().diagnose([symptom], store)
        assert diagnosis.proposal is not None
        assert diagnosis.proposal.action_id == "cam.device.enable"

    def test_candidates_and_predicates_are_registered(self) -> None:
        assert CANDIDATES["CAM.BLOCKED_BY_PRIVACY"] == ("privacy.allow",)
        assert CANDIDATES["MIC.BLOCKED_BY_PRIVACY"] == ("privacy.allow",)
        assert CANDIDATES["CAM.DEVICE_DISABLED"] == ("cam.device.enable",)
        for action in ("privacy.allow", "cam.device.enable"):
            assert REGISTRY.get(action).verify.predicate.id in PREDICATES


class TestVerification:
    def test_the_check_reads_the_setting_back(self, store: ObservationStore) -> None:
        predicate = PREDICATES["privacy.allowed"]
        args = {"capability": "webcam", "scope": "user"}

        consent(store, "camera", user="Deny")
        assert predicate(store, args)[0] is False

        consent(store, "camera", user="Allow")
        assert predicate(store, args)[0] is True

    def test_an_unset_value_counts_as_allowed(self, store: ObservationStore) -> None:
        store.ingest(
            [
                make_observation(
                    "privacy.camera",
                    {"capability": "webcam", "user": None, "machine": None, "denied_apps": []},
                )
            ]
        )
        passed, detail = PREDICATES["privacy.allowed"](
            store, {"capability": "webcam", "scope": "user"}
        )
        assert passed is True and "allows it" in detail
