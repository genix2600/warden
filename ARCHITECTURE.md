# How Warden works

Warden watches a Windows machine, works out what is wrong from readings it can
show you, proposes one specific fix, waits for you to approve it, runs it, and
then **re-measures to check whether it actually worked**. If it cannot verify a
fix it says so. If the cause is physical it refuses to invent a software fix and
routes the problem to a person.

This document is the map. If you are reviewing the code, the three files worth
reading first are:

| File | Why |
|---|---|
| [`warden/contracts/`](warden/contracts/) | Every type that crosses a boundary. Frozen, imports nothing else in the package. Read `diagnosis.py` first — it enforces the routing rule in the type system. |
| [`warden/playbooks/base.py`](warden/playbooks/base.py) | The closed action registry. Everything Warden can do to a machine is declared here, with a grounding guard and a verification predicate. |
| [`warden/executor/runner.py`](warden/executor/runner.py) | The only code that changes the machine, and the four gates in front of it. |

---

## The pipeline

One tick, end to end. Each stage is a separate module and each hands the next a
contract type, never a dict.

```
  collectors/          store.py          detectors/         reasoner/
 ┌───────────┐       ┌──────────┐      ┌───────────┐      ┌───────────┐
 │ 13 probes │──────▶│ readings │─────▶│ symptoms  │─────▶│ hypothesis│
 │ PowerShell│  Obs- │ with     │ Obs- │ debounced │Symp- │ local LLM │
 │ WMI/CIM   │ erva- │ history  │ erva-│ + root-   │tom   │ or rules  │
 │ psutil    │ tion  │          │ tion │ cause     │      │           │
 └───────────┘       └──────────┘      │ suppressed│      └─────┬─────┘
                                       └───────────┘            │
                                                                ▼
                                                    reasoner/guardrail.py
                                                   ┌────────────────────┐
                                                   │ is this action in  │
                                                   │ the candidate set  │
                                                   │ for THIS symptom?  │
                                                   │ are the params     │
                                                   │ grounded in a real │
                                                   │ reading?           │
                                                   └─────────┬──────────┘
                                                             │ Diagnosis
                        ┌────────────────────────────────────┴─────────┐
                        │                                              │
                        ▼ verdict = actionable                         ▼ verdict = needs_service
              ┌───────────────────┐                          ┌───────────────────┐
              │  THE HUMAN GATE   │                          │ service advice.   │
              │  no timer,        │                          │ No proposal — the │
              │  no default,      │                          │ contract forbids  │
              │  no auto-approve  │                          │ carrying one.     │
              └─────────┬─────────┘                          └───────────────────┘
                        │ approved_at
                        ▼
              executor/runner.py ──▶ executor/verifier.py ──▶ did it work?
              4 gates, shell=False    re-measure the           ├─ yes  → resolved
              argv list only          predicate declared       ├─ no   → escalate,
                                      BEFORE approval          │         excluding
                                                               │         what failed
                                                               └─ can't tell → say so
```

The loop lives in [`warden/orchestrator/agent.py`](warden/orchestrator/agent.py).
Nothing slow runs on the event loop: collectors go to a thread pool, a diagnosis
is a detached task because a local model can take twenty seconds, and telemetry
keeps flowing while it thinks.

---

## Why the model cannot run arbitrary commands

This is the question worth being precise about, because "an LLM that fixes your
computer" should worry you.

**The model never composes a command.** It receives a symptom and a set of
candidate action ids, and its entire output is a choice from that set plus
parameters. Commands live in
[`warden/playbooks/`](warden/playbooks/) as argv templates, written by hand,
checked at import.

Then four gates in [`warden/executor/runner.py`](warden/executor/runner.py):

1. **Approval.** `execute()` requires an `approved_at` timestamp. Keyword-only,
   no default, no `force` flag, and no code path that supplies one on the user's
   behalf. `tests/test_approval_gate.py` asserts this by inspecting the function
   signature, so a refactor cannot quietly remove it.
2. **Registry membership.** The action id must name a real playbook.
3. **Re-derivation.** The argv is rendered *again*, here, from the registry
   template and the proposal's parameters, and compared against the argv the
   proposal is carrying. If they differ, it is refused. Nothing downstream of the
   reasoner is trusted to hand the executor a command — not even Warden's own
   earlier self.
4. **Privilege.** An action needing elevation is refused up front rather than
   attempted and failed halfway through.

And throughout: `shell=False`, argv lists only. There is no shell in the
process, so there is nothing to inject into.

Two more checks sit earlier, in
[`warden/reasoner/guardrail.py`](warden/reasoner/guardrail.py):

- The action must be in the candidate set **for this symptom**, not merely
  somewhere in the registry — so a model cannot answer a full disk by restarting
  the wireless adapter.
- Parameters must survive the playbook's grounding guard, which checks them
  against observed reality — so a model cannot invent a network name or a device
  path that does not exist on this machine.

Refusals are recorded on the diagnosis and shown in the interface. "The model
suggested this and Warden would not run it" is information you are entitled to.

---

## Verification is the point

A troubleshooter that reports success without checking is the thing this project
exists to replace.

Every action declares a **verification predicate before approval is requested**,
so the definition of success is fixed before anyone agrees to anything. After
execution the predicate re-measures the machine —
[`warden/executor/verifier.py`](warden/executor/verifier.py).

Predicates are **tri-state**. `True`, `False`, and `None` for *inconclusive*,
which is never folded into `False`. "It did not work" and "I could not tell"
are different sentences and the user gets the right one.

When verification fails, the incident does not close. It re-enters the reasoner
with the failed action in an `exclude` set, so the next proposal has to be a
different one. That escalation path is the difference between an agent and a
script.

---

## What it refuses to do

Coverage is bounded by what can be verified. Where a domain has no verifiable
software fix, Warden detects the fault, presents the evidence, and routes it to a
human — that is a covered domain, not a gap.

**Seven symptoms are mapped to an empty candidate tuple** in
[`warden/playbooks/__init__.py`](warden/playbooks/__init__.py) — a deliberate,
declared "there is no software fix for this":

```
NET.INTERNET.UNREACHABLE     NET.WIFI.RADIO_OFF        NET.WIFI.NO_ADAPTER
THERMAL.SUSTAINED_THROTTLE   THERMAL.HIGH_TEMPERATURE
POWER.BATTERY_WORN           STORAGE.DISK_UNHEALTHY
```

A worn battery is not fixable with a command, and a tool that pretends otherwise
is lying to you. `_check_coverage()` fails the build if any symptom is left
unmapped, so this stays honest as the code grows.

The routing rule is enforced in the type system, not by convention —
[`warden/contracts/diagnosis.py`](warden/contracts/diagnosis.py) refuses to
construct a `needs_service` verdict that carries an executable proposal.

Also excluded, each on purpose:

| Excluded | Why |
|---|---|
| Malware removal | Cannot be done safely or verifiably. Warden reports Defender's status and stops. |
| Boot / BCD repair | Not fixable from a running session. |
| User profile corruption | Remediation is destructive and unverifiable. |
| Registry "cleaning" | No measurable benefit. Scareware's signature move. |
| Wrapping Windows' own troubleshooters | `Invoke-TroubleshootingPack` applies its own fixes with no reliable detect-only mode. That would drive changes to the machine around the approval gate, breaking the one guarantee Warden sells. MSDT is also being retired. |

---

## Why the model is local

[`warden/reasoner/llm.py`](warden/reasoner/llm.py) talks to Ollama on
`127.0.0.1`. This is a functional requirement before it is a privacy one: **a
cloud model cannot help you fix a network that is down.** It also means there is
no API key anywhere in this repository, and nowhere for one to be added — a
property of the design rather than a policy.

If no model is present, [`warden/reasoner/rules.py`](warden/reasoner/rules.py)
produces the same `Diagnosis` type through deterministic rules, and the interface
says which one answered. Warden degrades, visibly, rather than failing.

---

## Layout

| Directory | Holds |
|---|---|
| `contracts/` | Frozen wire types. Imports nothing else in the package. |
| `collectors/` | 13 probes. `psbridge.py` keeps one warm PowerShell host (~100 ms per call, versus ~500 ms cold). |
| `store.py` | Readings with history, so a detector can ask "for how long". |
| `detectors/` | Pure functions of the store. Debounced; root causes suppress their symptoms. |
| `reasoner/` | Local model, deterministic fallback, and the guardrail between them and the registry. |
| `playbooks/` | The closed action set: argv template, params model, grounding guard, verification predicate. |
| `executor/` | The four gates, and the re-measurement. |
| `orchestrator/` | The tick loop, the event bus, and session recording. |
| `domains.py` | Translates `CAM.BLOCKED_BY_PRIVACY` into "your camera". 13 user-facing areas. |
| `paths.py` | What ships with Warden versus what belongs to the user. |
| `api/` | FastAPI. TypeScript types are generated from these models, never hand-written. |

Thresholds are not scattered through detector code. They are in
[`warden/config.py`](warden/config.py), one reviewable place, and every one of
them was measured — the runs are recorded in
[`docs/calibration.md`](docs/calibration.md).
