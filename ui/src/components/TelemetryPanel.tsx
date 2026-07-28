import type { CollectorHealth, Observation, StatusTone } from "../types";
import { Sparkline } from "./Sparkline";
import { StatusDot } from "./StatusDot";

interface Props {
  telemetry: Record<string, Observation>;
  series: Record<string, number[]>;
  collectors: CollectorHealth[];
  onInspect: (observation: Observation) => void;
}

function num(observation: Observation | undefined): number | null {
  return typeof observation?.value === "number" ? observation.value : null;
}

function obj(observation: Observation | undefined): Record<string, unknown> {
  return observation && typeof observation.value === "object" && observation.value !== null
    ? (observation.value as Record<string, unknown>)
    : {};
}

/** Render a value out of an observation payload, which is deliberately untyped.
 *
 * An `Observation.value` is `JsonValue` on the wire because collectors return
 * genuinely heterogeneous shapes. Coercing at the point of display -- rather
 * than casting the whole payload to an invented interface -- keeps the lie out
 * of the type system. */
function text(value: unknown, fallback = "–"): string {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return fallback;
}

/** A single current value. Not every number needs a chart -- most need a tile. */
function Tile({
  label,
  value,
  unit,
  note,
  tone = "idle",
  observation,
  onInspect,
}: {
  label: string;
  value: string;
  unit?: string;
  note?: string;
  tone?: StatusTone;
  observation?: Observation;
  onInspect: (o: Observation) => void;
}) {
  return (
    <button
      type="button"
      disabled={!observation}
      onClick={() => observation && onInspect(observation)}
      className="group rounded-lg border border-hairline bg-surface p-3 text-left transition-colors enabled:hover:border-white/20 enabled:hover:bg-raised disabled:cursor-default"
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wide text-muted">{label}</span>
        {tone !== "idle" && <StatusDot tone={tone} />}
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="text-2xl font-semibold text-ink">{value}</span>
        {unit && <span className="text-xs text-ink-2">{unit}</span>}
      </div>
      {note && <div className="mt-0.5 truncate text-[11px] text-muted">{note}</div>}
      {observation && (
        <div className="mt-1 hidden text-[10px] text-muted group-hover:block">
          click to see how this was read
        </div>
      )}
    </button>
  );
}

export function TelemetryPanel({ telemetry, series, collectors, onInspect }: Props) {
  const link = obj(telemetry["net.wifi.link"]);
  const clock = obj(telemetry["cpu.clock"]);
  const memory = obj(telemetry["sys.memory"]);
  const provider = obj(telemetry["thermal.provider"]);
  const volumes = Array.isArray(telemetry["sys.disk.volumes"]?.value)
    ? (telemetry["sys.disk.volumes"]!.value as Record<string, unknown>[])
    : [];
  const system = volumes.find((v) => String(v.mount).startsWith("C"));

  const cpu = num(telemetry["sys.cpu.percent"]);
  const temperature = num(telemetry["thermal.cpu_c"]);
  const signal = num(telemetry["net.wifi.signal_pct"]);
  const ratio = typeof clock.ratio_pct === "number" ? clock.ratio_pct : null;

  const connected = link.state === "connected";
  const freeGb = typeof system?.free_gb === "number" ? system.free_gb : null;

  return (
    <div className="flex h-full flex-col gap-4">
      <section>
        <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Live readings
        </h2>
        <div className="grid grid-cols-2 gap-2">
          <Tile
            label="Processor"
            value={cpu === null ? "–" : cpu.toFixed(0)}
            unit="%"
            note={
              typeof clock.model === "string"
                ? clock.model.replace(/\((R|TM)\)/g, "")
                : undefined
            }
            observation={telemetry["sys.cpu.percent"]}
            onInspect={onInspect}
          />
          <Tile
            label="Temperature"
            value={temperature === null ? "n/a" : temperature.toFixed(0)}
            unit={temperature === null ? undefined : "°C"}
            note={
              temperature === null
                ? "no sensor; using clock evidence"
                : `via ${String(provider.active ?? "sensor")}`
            }
            tone={temperature !== null && temperature >= 90 ? "warning" : "idle"}
            observation={telemetry["thermal.cpu_c"] ?? telemetry["thermal.provider"]}
            onInspect={onInspect}
          />
          <Tile
            label="Wireless"
            value={connected ? `${signal?.toFixed(0) ?? "–"}` : "Down"}
            unit={connected ? "%" : undefined}
            note={connected ? String(link.ssid ?? "") : String(link.state ?? "unknown")}
            tone={connected ? "idle" : "critical"}
            observation={telemetry["net.wifi.link"]}
            onInspect={onInspect}
          />
          <Tile
            label="Memory"
            value={typeof memory.percent === "number" ? memory.percent.toFixed(0) : "–"}
            unit="%"
            note={
              typeof memory.available_mb === "number"
                ? `${(memory.available_mb / 1024).toFixed(1)} GB free`
                : undefined
            }
            tone={typeof memory.percent === "number" && memory.percent > 90 ? "warning" : "idle"}
            observation={telemetry["sys.memory"]}
            onInspect={onInspect}
          />
        </div>
      </section>

      <section className="rounded-lg border border-hairline bg-surface p-3">
        <div className="mb-1 flex items-baseline justify-between">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            Load against delivered speed
          </h2>
          {ratio !== null && (
            <span className="font-mono text-[11px] text-ink-2 tabular-nums">
              {text(clock.current_mhz)} / {text(clock.max_mhz)} MHz
            </span>
          )}
        </div>
        <Sparkline
          series={[
            {
              label: "Processor busy",
              values: series["cpu.busy_pct"] ?? [],
              color: "var(--color-series-2)",
            },
            {
              label: "Clock delivered",
              values: series["cpu.performance_pct"] ?? [],
              color: "var(--color-series-1)",
            },
          ]}
        />
        <p className="mt-1.5 text-[11px] leading-snug text-muted">
          When the orange line stays high and the blue line falls away, the processor is
          being held back by heat rather than by anything you can change.
        </p>
      </section>

      <section className="min-h-0 flex-1">
        <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Collectors
        </h2>
        <ul className="space-y-1">
          {collectors.map((collector) => (
            <li
              key={collector.id}
              className="flex items-center gap-2 rounded border border-hairline bg-surface px-2 py-1.5"
              title={collector.last_error ?? collector.description}
            >
              <StatusDot tone={collector.healthy ? "good" : "critical"} />
              <span className="font-mono text-[11px] text-ink-2">{collector.id}</span>
              <span className="ml-auto text-[10px] text-muted">{collector.interval_s}s</span>
            </li>
          ))}
        </ul>
        {freeGb !== null && (
          <p className="mt-2 text-[11px] text-muted">
            Drive C: {freeGb.toFixed(0)} GB free of{" "}
            {typeof system?.total_gb === "number" ? system.total_gb.toFixed(0) : "–"} GB
          </p>
        )}
      </section>
    </div>
  );
}
