"""One detector covering six subsystems, keyed on start type rather than status.

The naive version of this checks whether a service is running and reports a fault
if it is not. That version cries wolf constantly, and measuring the development
machine shows exactly why: ``wuauserv`` -- Windows Update -- is *stopped* right
now, and that is completely normal. Its start type is Manual, so Windows starts
it on demand and stops it again when it is finished.

So the rule is about the gap between how a service is configured and what it is
doing:

* **Automatic but stopped** — it was meant to be running and is not. A fault.
* **Disabled** — someone turned it off, and it will never start on its own. A
  fault, and a different one: restarting it is not enough, the start type has to
  change too.
* **Manual and stopped** — normal on-demand behaviour. Silence.
* **Absent** — the machine has no such hardware. A desktop with no Bluetooth
  genuinely has no ``bthserv``, and reporting that as broken would be a false
  alarm on a large fraction of machines.
"""

from __future__ import annotations

from warden.collectors.services import BY_NAME, start_type_name, status_name
from warden.contracts import Severity, Symptom
from warden.detectors.base import Detector
from warden.store import ObservationStore, as_dict, as_float, as_list

_RUNNING = 4
_AUTOMATIC = 2
_DISABLED = 4


class ServiceDetector(Detector):
    id = "sys.services"
    raises = tuple(service.symptom_code for service in BY_NAME.values())

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("sys.services")
        if observation is None:
            return []

        symptoms: list[Symptom] = []
        for raw in as_list(observation.value):
            row = as_dict(raw)
            watched = BY_NAME.get(str(row.get("name")))
            if watched is None or not row.get("present"):
                continue

            status = as_float(row.get("status"))
            start_type = as_float(row.get("start_type"))
            if status is None or int(status) == _RUNNING:
                continue

            disabled = start_type is not None and int(start_type) == _DISABLED
            automatic = start_type is not None and int(start_type) == _AUTOMATIC
            if not disabled and not automatic:
                continue  # Manual and stopped: on-demand, working as designed.

            symptoms.append(
                self.symptom(
                    watched.symptom_code,
                    severity=Severity.CRITICAL,
                    title=(
                        f"The Windows {watched.subsystem} service is turned off"
                        if disabled
                        else f"The Windows {watched.subsystem} service has stopped"
                    ),
                    detail=(
                        f"{row.get('display_name')} ({watched.name}) is "
                        f"{status_name(row.get('status'))} with start type "
                        f"{start_type_name(row.get('start_type'))}, so "
                        f"{watched.consequence}."
                    ),
                    facts={
                        "service": watched.name,
                        "display_name": row.get("display_name"),
                        "subsystem": watched.subsystem,
                        "status": status_name(row.get("status")),
                        "start_type": start_type_name(row.get("start_type")),
                        # A disabled service will not survive a plain restart --
                        # the start type has to be changed as well, which is a
                        # different and more intrusive action.
                        "is_disabled": disabled,
                        "consequence": watched.consequence,
                    },
                    evidence=[observation],
                )
            )
        return symptoms
