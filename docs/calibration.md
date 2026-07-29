# Threshold calibration

Every number in `warden/config.py` came from a measurement on real hardware, not
from a guess. This file is the measurement, so the thresholds can be argued with.

## Run 1 — thermal, 28 July 2026

**Machine.** Dell laptop, Intel Core i5-1135G7 (4 cores / 8 threads, 2.4 GHz
base), 16 GB RAM, Windows 11 build 26220. Warden running as a standard user with
no sensor library present, which is the worst case for temperature data and
therefore the case worth calibrating against.

**Method.** `POST /api/demo/cpu-load` saturates every core with SHA-256 digests
over a 4 MB buffer — real work, not a spin loop, and hashlib releases the
interpreter lock so all eight threads genuinely run. Warden's own telemetry was
sampled through `GET /api/state` every 5 s, so the numbers below are exactly what
the detector sees rather than a parallel measurement that might disagree.

**Results.**

| Signal | Baseline | Sustained 100% load (steady state, n=27) |
|---|---|---|
| `cpu.busy_pct` | 51–97% (noisy, see below) | 100% flat |
| `cpu.performance_pct` | mean 89.3% | **mean 90.6%, min 88%, max 94%** |
| `cpu.clock.ratio_pct` | 100% | **100% — never moved** |
| `thermal.cpu_c` | unavailable | unavailable |

## What this established

**1. `Win32_Processor.CurrentClockSpeed` is inert on this hardware.** It reported
2419 MHz — exactly `MaxClockSpeed` — at idle and under a three-minute all-core
burn alike. Windows is reporting the rated base clock, not the delivered one. Any
detector keyed on that ratio would be keyed on a constant. It is still collected
and shown as context, but nothing decides anything on it. This is why the
throttle detector reads `PercentProcessorPerformance` from the performance
counter class instead, which does move.

**2. This machine does not thermally throttle, and Warden correctly says so.**
Delivered performance held at 88–94% through three minutes at full load. That is
a cooling system doing its job. With `throttle_performance_pct = 85`, the
detector stays silent here — which is the right answer, and worth stating plainly
because the temptation when building a demo is to lower the threshold until
something fires. A tool that invents a fault to look impressive is the tool this
project exists to replace.

The 85% line sits just below the observed healthy floor of 88%, so it separates
"working as designed" from genuine throttling without being tuned so tight that
normal variation trips it. A machine with a dust-blocked heatsink drops to the
50–70% range under the same load; that is what the severe threshold at 70% is
for.

**3. The baseline was not idle, and that is a finding too.** `cpu.busy_pct` read
51–97% during the "idle" phase because the sampling script, the PowerShell host
and a browser were all running. It is why the throttle detector requires
*sustained load AND depressed performance together* rather than either alone —
on a real desktop, "the processor is busy" carries almost no information by
itself.

## Consequence for the demonstration

The thermal scenario on this machine ends in "nothing is wrong here, and here is
the evidence" rather than in a servicing recommendation. That is an honest
outcome but a quiet one, so the hardware-versus-software routing is better shown
with **`NET.WIFI.RADIO_OFF`**: switching on airplane mode is a real physical
action, takes one keystroke, is completely reproducible, and produces a symptom
for which the action registry deliberately contains no command. Warden routes it
to `NEEDS_SERVICE` with `who: "user"` and tells the operator to flip the switch —
the same routing logic, on a symptom that fires on demand.

## Run 2 — wireless reconnect latency, 28 July 2026

**Method.** `netsh wlan disconnect`, then `netsh wlan connect` to the profile
last in use, polling interface state once per second.

| Attempt | Result |
|---|---|
| 1 | associated in 11.5 s |
| 2 | `netsh` reported success; never associated within 45 s |
| 3 | `netsh` reported success; never associated within 45 s |

**What this established.** `netsh wlan connect` returns "Connection request was
completed successfully" as soon as the request is *queued*, not when it succeeds.
On this machine the request frequently loses a race with the WLAN AutoConfig
service, which is scanning and trying its own profile list at the same time. Two
consequences, both already in the design:

- **Exit code 0 is not success.** This is the concrete justification for the
  verifier: the command's own report of success is worthless here, and only
  re-reading the adapter tells the truth.
- **One fix attempt is not enough.** It is why a failed verification escalates to
  the next action in the candidate list rather than closing the incident. The
  ladder for a dropped wireless link is reconnect → scan → restart the adapter,
  each requiring its own approval.

The verification window for `net.wifi.reconnect` is set to 25 s from the 11.5 s
success case plus margin. Waiting longer would not help: the failures did not
become successes at 45 s, they stayed failures, and a fix that has not taken hold
in twice its typical time is better escalated than waited on.

---

## Local model latency, and why the model is small

**Measured 29 July 2026, on the development machine.** i5-1135G7, 4 cores / 8
threads, Iris Xe integrated graphics, no discrete GPU, 15.8 GB RAM. Inference is
CPU-only; there is no offload path on this hardware.

The prompt is the real one, built by `build_user_prompt` from a
`NET.WIFI.DISCONNECTED` symptom with four supporting readings and three candidate
actions — 2,211 characters.

| Run | `qwen2.5:1.5b-instruct`, model resident |
|---|---|
| 1 | 18.7 s |
| 2 | 15.4 s |
| 3 | 15.1 s |

The first call after a cold start is different and worth stating separately: it
exceeded 25 s, because roughly a gigabyte of weights has to be read off disk
before any token is produced. That cost is paid once, which is why the client
sends `keep_alive: -1` and the runtime is started before the agent rather than
lazily on the first incident.

**Why not a larger model.** A 7B model on this machine produces 4–6 tokens per
second. A decision of this shape is 250–400 tokens, so it would take 60–100 s and
never complete inside any ceiling worth having. It would not be slow, it would be
non-functional: every incident would fall back to the rules engine after a 4.7 GB
download. The interface would say `rules engine` and a reasonable person would
conclude the product has no model in it at all.

**What the small model gets wrong, and why that is survivable.** Across three
runs it consistently returned `needs_more_data` and chose `net.wifi.scan` — a
valid action from the candidate set, and the timid one. With a saved profile
present, `net.wifi.reconnect` is the better first move.

This is tolerable because of a property the system already had. The scan is
read-only, verification re-reads the adapter and finds it still disassociated,
and the incident escalates with `net.wifi.scan` added to the `exclude` set, so
the next proposal cannot be the same one. A conservative first guess costs one
extra approval, not a wrong outcome. It is also, demonstrated live, the clearest
evidence that the loop is an agent rather than a script.

**Threshold set from this.** The client ceiling moved from 25 s to 45 s. 25 s was
under 1.5x the observed mean, which is not headroom — it is a coin toss on any
machine slower than this one, and the build is meant to be shared with machines
nobody here has measured.
