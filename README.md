# Warden

**An agentic Windows diagnostician that reads your actual machine, shows you its
evidence, and runs nothing without your say-so.**

Windows' built-in troubleshooters run a scripted checklist and usually close
without finding anything. AI chatbots can discuss your symptoms but never look at
your computer — they cannot read your logs, check what is installed, or confirm a
fix worked. You end up doing the real diagnostic work yourself: translating an
error into a search query, trying a fix blind, repeating until something sticks.

Warden closes that loop. It watches real system signals, reasons over them,
proposes one specific command with the readings that justify it, waits for you to
approve, runs it, and then **re-reads the machine to check whether it actually
worked**. When the cause is physical, it says so and routes you to a fix a
command cannot perform.

---

## What makes it different

**It shows its work.** Every number Warden displays carries the exact command
that produced it, how long that took, and how much the collector trusts it. Click
any reading and you get a command you could run yourself and get the same answer.

**It cannot invent a command.** The reasoning model never writes shell. It picks
an id from a closed registry of seven reviewed actions and supplies parameters,
which are validated against a schema *and* against reality before a human is ever
asked to approve them. Warden will not connect you to a network it has never seen
this machine use, or restart a device that is not in the device tree.

**It knows what it cannot fix.** The mapping from symptom to available actions is
data, in `warden/playbooks/__init__.py`. Five symptoms map to an empty tuple —
overheating, a radio switched off in hardware, no adapter present, an upstream
internet fault. For those there is no command in the candidate set to choose, so
no amount of model confidence can produce one. It routes to servicing instead,
and distinguishes "you need to flip a switch" from "this needs a technician".

**"Fixed" is a measurement, not a claim.** Each action declares its own success
test *before* you approve it, so you approve both the command and the standard it
will be judged by. Afterwards Warden re-runs the relevant collectors and
evaluates that test. If it fails, it escalates to the next step rather than
declaring victory.

**It works with the network down.** The model runs locally, through Ollama. This
is a requirement, not a cost decision: a diagnostician that needs the internet to
explain why you have no internet is useless. It also means there is no API key in
this repository, and none anywhere else — your event log, device inventory and
network configuration never leave the machine.

**It works without the model too.** A deterministic rules engine handles every
scenario end to end. The model improves the writing and the ranking; it is not
load-bearing for correctness, and the interface always tells you which one
answered.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2 | Best Windows introspection surface (WMI/CIM, PDH, pywin32, pythonnet); Pydantic gives typed contracts the front end is generated from |
| Desktop shell | pywebview on WebView2 | A real desktop window at ~10 MB, using the browser engine Windows 11 already ships. One runtime instead of Electron's two |
| Interface | React 18, TypeScript, Vite, Tailwind v4 | Types are **generated** from the backend's OpenAPI document, never hand-written |
| Local model | Ollama, `qwen2.5:7b-instruct` | Schema-constrained JSON decoding; runs on a laptop; no account, no key |
| System access | PowerShell CIM/Net cmdlets over a persistent host, `psutil`, `netsh`, ACPI/WMI, optional LibreHardwareMonitor via pythonnet | Locale-independent where it matters; see below |
| Tests | pytest — 62 tests, no hardware required | The whole detection and reasoning layer runs on any machine |
| Quality | ruff (lint + format) clean, mypy clean across all 46 modules, strict on `contracts/` | |

### Two implementation details worth a look

**A persistent PowerShell host** (`warden/collectors/psbridge.py`). Warden reads
the machine through CIM classes and `Get-Net*` cmdlets rather than by scraping
`netsh` text, because CIM property names are locale-independent and `netsh`
output is not — a parser built on English output silently reports nothing on a
German install. The cost is process startup, about half a second per
`powershell.exe`, which at a 2-second poll across seven collectors would eat the
machine we are meant to be diagnosing. So Warden starts one host, holds it open,
and streams single-line commands into it against a sentinel. Steady-state cost
drops to **under 100 ms per probe**.

**Temperature, and its absence** (`warden/collectors/thermal.py`). There is no
supported universal API for CPU temperature on Windows. Warden tries four
providers in order and reports which one answered with a confidence value the
rest of the system respects — real sensors, an existing monitor's WMI namespace,
ACPI thermal zones, and finally throttle inference from performance counters,
which needs no driver and no elevation and always works. The detector fuses load
and delivered clock rather than keying on degrees, because "the machine has gone
slow" is the thing users actually experience and degrees are only a proxy for it.

---

## Running it

```powershell
git clone <this repo>
cd warden
.\run.ps1
```

`run.ps1` creates the virtual environment, installs dependencies, builds the
interface and opens the window. First launch takes a couple of minutes; after
that, startup is about 15 seconds — most of it PowerShell loading its networking
modules, which Warden pays once at startup rather than on the first poll.

**Optional, both degrade honestly if skipped:**

```powershell
ollama pull qwen2.5:7b-instruct   # written explanations instead of templated ones
.\scripts\fetch-sensors.ps1       # real temperatures (also needs an elevated run)
```

**Check it is ready** — the `Readiness` button in the interface, or:

```powershell
.\scripts\doctor.ps1
```

**Development:**

```powershell
python -m warden --headless --port 8099   # backend only, browsable API at /docs
cd ui && npm run dev                       # interface with hot reload
python -m pytest                           # 60 tests, ~2s, no hardware needed
cd ui && npm run gen:types                 # regenerate TS types from the contracts
```

---

## Seeing it work

The **Fault injection** bar at the bottom of the window breaks the machine for
real. Nothing in Warden synthesises telemetry — there is deliberately no code
path that can — so a demonstration exercises the same collectors, detectors and
verifier that a genuine fault would.

**Wireless drop.** `Drop wireless` really disconnects the adapter. Within about
four seconds Warden raises `NET.WIFI.DISCONNECTED`, works out which network to
restore from *its own observation history* rather than from a saved-profile list,
and proposes `netsh wlan connect`. Approve it and it reconnects, then re-reads
the adapter to confirm. If the reconnect does not take — which on our development
machine happens roughly two times in three, see `docs/calibration.md` — Warden
does not give up: it escalates to the next action on the ladder and asks again.

**Radio off.** Turn on airplane mode. Warden raises `NET.WIFI.RADIO_OFF`, and
because that symptom maps to an empty action list, it cannot propose a command.
It tells you to flip the switch instead.

**Sustained load.** `Load all cores` runs a real all-core burn. On a healthy
machine Warden stays quiet, which is the correct answer — see below.

---

## What we measured, including the inconvenient parts

`docs/calibration.md` records the runs that produced every threshold in
`warden/config.py`. Two findings worth stating plainly here:

**The development laptop does not thermally throttle.** Under three minutes at
100% on all cores it held 88–94% of its rated clock. The honest conclusion is
that its cooling works, so Warden stays silent, and a test pins those real
numbers so nobody can quietly lower the threshold until something fires. A tool
that invents a fault to look impressive is the tool this project exists to
replace.

**`Win32_Processor.CurrentClockSpeed` is inert.** It reported exactly
`MaxClockSpeed` at idle and under full load alike. Any detector keyed on that
ratio would be keyed on a constant. This is why the throttle signal comes from
`PercentProcessorPerformance` instead.

**`netsh wlan connect` reports success before it has succeeded.** Measured three
times: 11.5 s, never, never. Exit code zero is not evidence — which is the
concrete reason the verifier exists and the reason a failed verification
escalates rather than closing the incident.

---

## Repository layout

```
warden/
  contracts/     Frozen wire types. Imports nothing else in the package;
                 everything else imports these. Read this directory first.
  collectors/    Read the machine. No interpretation, no decisions.
  detectors/     Turn readings into symptoms. Deterministic, no model.
  playbooks/     The closed action registry, its grounding guards, and the
                 symptom -> action map that encodes what cannot be fixed.
  reasoner/      Rules engine, local model client, prompt, guardrail.
  executor/      Approval-gated runner (argv only, never a shell) + verifier.
  orchestrator/  The loop, the event bus, session recording and replay.
  demo/          Real fault injection. Fenced off; the agent cannot reach it.
  api/           FastAPI + WebSocket, bound to loopback only.
ui/              React interface; src/generated/ is produced, not written.
tests/           60 tests, none of which need Windows-specific hardware.
docs/            Architecture and the calibration measurements.
```

Start with `warden/contracts/` — the type definitions carry the design, and the
rule that a `NEEDS_SERVICE` verdict is structurally incapable of holding an
executable proposal is enforced there, in `diagnosis.py`, by a model validator.

`ARCHITECTURE.md` explains why the pieces are arranged this way.

---

## Honest limitations

- **Windows only**, and tested on Windows 11 build 26220. It reads Windows-specific interfaces throughout.
- **Seven actions.** The registry is small on purpose; each entry is reviewed, grounded and verifiable. Breadth would come at the cost of the guarantees.
- **Real temperatures need elevation and a third-party library.** Without them Warden falls back to throttle inference, which is weaker but never absent.
- **The local model is optional and untested at scale.** Every scenario is handled by the rules engine; the model has been exercised against its schema, not across many machines.
- **No installer.** It runs from source. Packaging was not where the time belonged.
# warden
Windows diagnostician
