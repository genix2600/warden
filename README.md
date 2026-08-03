# Warden

**An agentic Windows diagnostician that reads your machine, shows you the evidence, and runs nothing without your say-so.**

`v1.0.0` · Windows 10 and 11, x64 · 364 tests · runs on your own machine by default

[Website](https://wardensys.vercel.app) · [Download](https://github.com/genix2600/warden/releases/latest) · [Architecture](ARCHITECTURE.md) · [Measurements](docs/calibration.md)

---

## The problem

Three kinds of tool exist to help when a computer misbehaves, and each fails in
its own way.

Windows' built-in troubleshooters run a scripted checklist and usually close with
"Troubleshooting couldn't identify the problem."

AI chatbots can discuss your symptoms but cannot see your computer. They cannot
read your event log, check what is installed, or confirm that a fix worked. You
end up acting as their hands and their eyes.

"PC optimisers" scan, report several thousand issues, and charge to fix them. The
issues are registry keys that do nothing, and the improvement is unmeasurable.
That is deliberate, because a claim nobody can check is a claim nobody can
disprove.

What none of them do is both read the machine and prove the fix.

## What Warden does

It watches real system signals. When you ask it to look into something, it reasons
over what it actually measured, proposes one specific command with the readings
that justify it, waits for your approval, runs it, and then re-reads the machine to
check whether the fix worked. If the cause is physical, it says so and tells you
what to take to a repair shop.

```
  read  ->  reason  ->  ask  ->  run  ->  prove  ->  escalate if it failed
```

The last two steps are the ones other tools skip.

### It shows its work

Every number Warden displays carries the command that produced it, how long that
took, and how much the collector trusts it. Click any reading and you get a
command you can run yourself to get the same answer.

### It cannot invent a command

The local model never writes shell. It chooses an id from a closed registry of
17 reviewed actions and supplies parameters, which are checked against a schema
and against reality before anyone is asked to approve them. Warden will not
connect you to a network it has never seen this machine use, or restart a device
that is not in the device tree.

The optional cloud model *may* write one, because seventeen actions cannot cover
an arbitrary Windows fault and pretending otherwise was the honest limit of the
first design. That path is quarantined rather than merged: a written command is
screened against a refusal list before you are shown it, runs as an argument
list with no shell, takes a restore point first, and is labelled in the
interface as written-by-the-model rather than reviewed. See **Two brains**.

### Watching is automatic, interrupting is not

Findings appear on the Health page and wait there. Nothing is diagnosed until you
press **Look into this** on an area or **Check everything**. A machine with no
printer is never told about the print spooler. Automatic diagnosis is available as
a setting for anyone who prefers it.

### It reviews settings that are wrong without being broken

Most of Warden reacts to faults. The **Tune-up** page is the standing review: a
processor capped at 60% by a power plan nobody chose, graphics drivers four years
old, automatic cleanup switched off. None of it is failing, which is exactly why
nobody has found it.

Two rules decide what appears there, both enforced in the contracts rather than
by good intentions. A finding must name a quantity Warden can read before and
after, so nothing on the page has a benefit you can only feel. And a fix must be
reversible, which is why the obvious one is missing: Warden measures the
gigabyte of temporary files it could delete, prints the figure, and does not
offer to delete it, because a deletion cannot be put back. It offers Storage
Sense instead.

Where there is no right answer it refuses to pick one. A capped processor is
faster plugged in or cooler on your lap, so Warden shows both costs, recommends
neither, and says why. After a change it re-reads the same number and reports the
difference, including when the difference is *"No measurable change yet"*.

### "Fixed" is a measurement

Each action declares its own success test *before* you approve it, so you approve
both the command and the standard it will be judged by. Afterwards Warden re-runs
the relevant collectors and evaluates that test. Verification has three answers
rather than two: it worked, it did not, or it could not tell. If it did not work,
Warden escalates to the next action on the ladder instead of declaring victory.

### It knows what it cannot fix

The map from symptom to available actions is data, in
`warden/playbooks/__init__.py`. Seven symptoms map to an empty tuple: overheating,
running too hot, a radio switched off in hardware, no wireless adapter present, an
upstream internet fault, a worn-out battery and a failing drive. For those there is
no command in the candidate set to choose, so no amount of model confidence can
produce one. A build-time check fails if any symptom is left unmapped.

### Two brains, and it always says which one answered

**Local, and the default.** Qwen2.5-1.5B on your own processor. Sends nothing
anywhere, confined to the seventeen reviewed actions, and keeps working when the
network is the thing that is broken. That last point is a functional requirement
before it is a privacy one: a diagnostician that needs the internet to explain
why you have no internet is useless in the situation it exists for. It is why
the local path can never be removed and why the cloud path can never be
required.

**Cloud, off until you turn it on.** A hosted model reached with a key you fetch
yourself. It knows the Windows command line properly and may write a command
when none of the seventeen fit, which is the only reason to reach for it. It
costs a round trip, needs a working connection, and sends the readings behind
the problem to a third party. The Model page states that above the key field
rather than below it.

This repository contains no API key. It never will: it is public, so a key in it
would be a key for everyone. If you supply one it is written to
`credentials.json` in your own user folder, kept out of the settings model so
the settings endpoint cannot return it, and shown back to you as four
characters.

### It works without the model too

A deterministic rules engine handles every scenario end to end. The model improves
the writing and the ranking without being load-bearing for correctness, and the
interface always says which one answered.

---

## Coverage

| | |
|---|---|
| Areas watched | 13, named the way a person would name them |
| Problems detected | 25 |
| Actions available | 17 reviewed (2 read-only, 9 reversible, 6 disruptive), plus composed commands in cloud mode |
| Problems refused | 7, enforced by an empty candidate list |
| Verification predicates | 14 |
| Collectors | 14, sampling from every 2 seconds to every 120 |
| Settings audited | 9 checks, 2 of which Warden can change and undo |

Internet and Wi-Fi · Sharing and Discovery · Printing · Sound · Camera and
Microphone · Bluetooth · Windows Update · Search · Battery · Storage · Speed and
Temperature · Devices and Drivers · Clock

---

## Install

### From a release

Download the installer from
[the latest release](https://github.com/genix2600/warden/releases/latest) and run
it. It installs per-user, asks for no administrator rights, and needs none to run.

The installer is 45 MB and contains the application and the local model runtime.
The model itself is about 1 GB and is downloaded on request from the Readiness
page, then kept under `%LOCALAPPDATA%\Warden` so an upgrade does not fetch it
again. Warden is usable before you do that, using the rules engine.

The build is unsigned, so SmartScreen shows "Windows protected your PC" on first
run. Choose **More info** then **Run anyway**. A code-signing certificate is the
only fix for that, and it is not something the source can change.

A zip is also attached to the release for machines that block installers. Extract
it and run `Warden.exe` from inside the folder, keeping the folder together.

### What it writes

| Path | Contents |
|---|---|
| `%LOCALAPPDATA%\Programs\Warden` | The application. Removed completely on uninstall. |
| `%LOCALAPPDATA%\Warden\sessions` | One record per run, so a decision can be reopened later. Uninstall asks first. |
| `%LOCALAPPDATA%\Warden\logs` | Plain-text log, the first place to look if something misbehaves. |
| `%LOCALAPPDATA%\Warden\models` | The model, once you ask for it. |
| `%LOCALAPPDATA%\Warden\settings.json` | Theme, behaviour, muted findings. Holds no credentials. |
| `%LOCALAPPDATA%\Warden\credentials.json` | Your cloud key, if you added one. Nothing else, and no API returns it. |

Nothing is written outside your user folder. Nothing is transmitted anywhere unless
you turn on the cloud model, and then only the readings behind the problem.

### From source

```powershell
git clone https://github.com/genix2600/warden
cd warden
.\run.ps1
```

`run.ps1` creates the virtual environment, installs dependencies, builds the
interface and opens the window. It is safe to run repeatedly, because every step
checks whether it is already done.

### Building the installer

```powershell
.\scripts\fetch-model.ps1 -RuntimeOnly   # stages ollama.exe, no weights
.\scripts\build-installer.ps1            # dist\Warden-Setup-1.0.0.exe
```

Drop `-RuntimeOnly`, then pass `-Offline` to `build-installer.ps1`, to build the
edition that carries the model inside it for machines that will never have a usable
connection. That one is roughly 967 MB.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2 | Best Windows introspection surface available (WMI/CIM, PDH, pywin32, pythonnet). Pydantic gives typed contracts the front end is generated from. |
| Desktop shell | pywebview on WebView2 | A real window at about 10 MB, reusing the browser engine Windows already ships. One runtime instead of Electron's two. |
| Interface | React 18, TypeScript, Vite, Tailwind v4 | Types are generated from the backend's OpenAPI document, never written by hand. |
| Cloud model (optional) | Groq, your own key, off by default | Reaches past the seventeen reviewed actions when nothing fits. Requires a connection, sends readings to a third party, and is labelled as such on every diagnosis. |
| Local model | Qwen2.5-1.5B via a bundled Ollama | Schema-constrained JSON decoding, so the model cannot emit prose where an action id belongs. Small on purpose, for reasons below. |
| System access | CIM and `Get-Net*` cmdlets over a persistent PowerShell host, `psutil`, `netsh`, ACPI/WMI, optional LibreHardwareMonitor via pythonnet | Locale-independent where it matters. |
| Packaging | PyInstaller (onedir) and Inno Setup | A folder rather than a self-extracting binary, which starts faster and trips fewer antivirus heuristics. |
| Website | Next.js, Tailwind v4, on Vercel | Nine static pages, no backend. |
| Quality | pytest, mypy, ruff | 364 tests needing no Windows hardware. mypy clean across 77 modules, strict on `contracts/`. |

### Why the model is small

Measured rather than assumed. On the development laptop (i5-1135G7, four cores,
integrated graphics, no discrete GPU) a 7B model produces 4 to 6 tokens per second,
so a decision of the shape Warden needs takes 60 to 100 seconds and never finishes
inside a sensible timeout. It would not be slow, it would be non-functional. The
1.5B answers the same prompt in 15.1 to 18.7 seconds.

The job also suits a small model. It picks a single id from a candidate list that
usually holds one entry, and writes two sentences inside a schema it cannot break.
That is classification plus short generation rather than open reasoning.

---

## Two implementation details worth reading

**A persistent PowerShell host** (`warden/collectors/psbridge.py`). Warden reads
the machine through CIM classes and `Get-Net*` cmdlets rather than by scraping
`netsh` text, because CIM property names are locale-independent and `netsh` output
is not. A parser built on English output silently reports nothing on a German
install. The cost is process startup, about half a second per `powershell.exe`,
which at a two-second poll across fourteen collectors would consume the machine it
is meant to be diagnosing. Warden starts one host, holds it open, and streams
single-line commands into it against a sentinel. Steady-state cost drops below
100 ms per probe.

**Temperature, and its absence** (`warden/collectors/thermal.py`). Windows has no
supported universal API for CPU temperature. Warden tries four providers in order
and reports which one answered, with a confidence value the rest of the system
respects: real sensors through LibreHardwareMonitor, an existing monitor's WMI
namespace, ACPI thermal zones, and finally throttle inference from performance
counters, which needs no driver and no elevation and always works. The detector
fuses load against delivered clock rather than keying on degrees, because "the
machine has gone slow" is what users actually experience and degrees are only a
proxy for it.

---

## What we measured, including the inconvenient parts

`docs/calibration.md` records the run behind every threshold in
`warden/config.py`. Four findings worth stating here.

**The development laptop does not thermally throttle.** Under three minutes at
100% on all cores it held 88 to 94% of its rated clock. The honest conclusion is
that its cooling works, so Warden stays silent, and a test pins those numbers so
nobody can quietly lower the threshold until something fires.

**`Win32_Processor.CurrentClockSpeed` is inert.** It reported exactly
`MaxClockSpeed` at idle and under full load alike. A detector keyed on that ratio
would be keyed on a constant, which is why the throttle signal comes from
`PercentProcessorPerformance` instead.

**`netsh wlan connect` reports success before it has succeeded.** Measured three
times: 11.5 seconds, never, never. Exit code zero is not evidence. That is the
concrete reason the verifier exists, and the reason a failed verification escalates
instead of closing the incident.

**`w32tm` reports a phase offset of zero when it has never reached a server.** The
zero means "no idea", not "accurate". Warden therefore reports an unsynchronised
clock as a note rather than a fault, because it cannot honestly say how wrong the
clock is.

---

## Seeing it work

The **Fault injection** bar at the bottom of the window breaks the machine for
real. Nothing in Warden synthesises telemetry and there is deliberately no code
path that could, so a demonstration exercises the same collectors, detectors and
verifier that a genuine fault would.

**Wireless drop.** `Drop wireless` disconnects the adapter. Within about four
seconds Warden raises `NET.WIFI.DISCONNECTED` on the Health page. Press **Look into
this** and it works out which network to restore from its own observation history
rather than from a saved-profile list, then proposes `netsh wlan connect`. Approve
it and Warden re-reads the adapter to confirm. If the reconnect does not take,
which happens roughly two times in three on the development machine, it escalates
to the next action and asks again.

**Radio off.** Turn on airplane mode. Warden raises `NET.WIFI.RADIO_OFF`, and
because that symptom maps to an empty action list it cannot propose a command. It
tells you to flip the switch.

**Sustained load.** `Load all cores` runs a real all-core burn. On a healthy
machine Warden stays quiet, which is the correct answer.

Every run records itself to a session file. Because the recording is the same event
stream the live interface consumes, a replayed session renders identically to a
live one, and the interface labels a replay permanently so a recording can never be
presented as live data.

---

## Repository layout

```
warden/
  contracts/     Frozen wire types. Imports nothing else in the package;
                 everything else imports these. Read this directory first.
  collectors/    Read the machine. No interpretation, no decisions.
  detectors/     Turn readings into symptoms. Deterministic, no model.
  audit/         The standing review of settings that are wrong but not broken.
  reasoner/      Rules engine, local model client, prompt, guardrail.
  playbooks/     The closed action registry, its grounding guards, and the
                 symptom to action map that encodes what cannot be fixed.
  executor/      Approval-gated runner (argv only, never a shell) and verifier.
  orchestrator/  The loop, the event bus, session recording and replay.
  demo/          Real fault injection. Fenced off; the agent cannot reach it.
  api/           FastAPI and WebSocket, bound to loopback only.
  domains.py     Translates symptom codes into the 13 areas people recognise.
  settings.py    User preferences. Separate from measured thresholds.
  paths.py       What ships with Warden versus what belongs to the user.
ui/              React interface. src/generated/ is produced, not written.
site/            The website. Vercel Root Directory must be set to site.
installer/       Inno Setup definition.
scripts/         Build, icon generation, model staging, schema export.
tests/           364 tests, none of which need Windows-specific hardware.
docs/            The calibration measurements behind every threshold.
```

If you read three files, read these in order:

1. `warden/contracts/` for the types, which carry the design. The rule that a
   `NEEDS_SERVICE` verdict cannot hold an executable proposal is enforced in
   `diagnosis.py` by a model validator rather than by convention.
2. `warden/playbooks/base.py` for everything Warden can do to a machine.
3. `warden/executor/runner.py` for the only code that changes anything, and the
   four gates in front of it.

[`ARCHITECTURE.md`](ARCHITECTURE.md) has the pipeline diagram, those four gates,
and the full list of what Warden refuses to attempt.

---

## Development

```powershell
python -m warden --headless --port 8099   # backend only, API docs at /docs
cd ui; npm run dev                        # interface with hot reload
python -m pytest                          # 364 tests, about 4 seconds
python -m mypy warden                     # 77 modules, strict on contracts/
python -m ruff check .; python -m ruff format .
cd ui; npm run gen:types                  # regenerate TS types from contracts
```

The TypeScript types in `ui/src/generated/` come from the backend's OpenAPI
document and are gitignored. Committing them would let a stale copy disagree with
the backend without anything failing.

Useful flags: `--no-llm` skips the model entirely, `--no-record` skips the session
file, `--model` overrides the model tag.

### The website

```powershell
cd site; npm install; npm run dev
```

One setting is not discoverable and the deployment fails without it: in the Vercel
project, set **Root Directory** to `site`. Otherwise Vercel finds `pyproject.toml`
at the repository root and tries to build the Python project.

---

## Limitations

**Windows only**, x64, tested on Windows 11 build 26220. Warden reads WMI, the
Windows event log, the registry and Windows services throughout, so there is no
meaningful cross-platform version of it.

**Seventeen actions.** The registry is small on purpose. Every entry is
reviewed, grounded against observed reality, and verifiable. Breadth would cost
the guarantees that make the rest defensible.

**A command the cloud model writes carries a weaker guarantee.** The seventeen
reviewed actions are grounded against readings actually taken from your machine
and verified afterwards by a predicate declared before you approve. A composed
command has neither: it is screened against a refusal list, shown to you exactly
as it will run, and that is the whole of it. Warden reports the exit code and the
output and does not claim the problem is fixed, because it has measured nothing.
The interface uses a different card for it for exactly this reason.

**Seven of the nine audit checks report without acting.** A check earns a fix
button only if the change can be undone and the quantity re-read afterwards.
Driver age, startup load and reclaimable space fail that test for good reasons
rather than for want of time, and the page says so where the button would be.

**No temperature sensor on many machines.** Without LibreHardwareMonitor in
`vendor/`, the thermal collector falls to inferring from delivered clock speed and
says so on the reading itself, rather than printing a plausible number.

**Measured on one machine.** Every latency figure in this README comes from a
single laptop. Behaviour on other silicon is reasoned about, not tested.

**Unsigned.** SmartScreen will warn until there is a certificate.

---

## Team

Built for ShriTeq 2026.

- **Aaryaman Vaidya** (technical lead)
- **Abhav Jain** (debugger)
- **Annem Saad** (tester)
- **Avyukt Chhabra** (front-end developer)
- **Viti Mehra** (presentation lead)

---

## Licence

See [LICENSE](LICENSE). The bundled model runtime (Ollama, MIT) and model weights
(Qwen2.5, Apache 2.0) are redistributed unmodified, with their notices inside the
application folder.
