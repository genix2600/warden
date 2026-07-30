import { useMemo, useRef, useState } from "react";

/**
 * Two percentage series on one axis, over time.
 *
 * Processor load and delivered clock are both percentages of the same
 * denominator, which is the only reason they may legitimately share an axis --
 * plotting two differently-scaled measures against two y-scales is the mistake
 * this deliberately does not make. Their relationship *is* the diagnosis: load
 * high while delivered clock falls away is thermal throttling, and seeing the
 * two lines separate is the fastest way to understand that.
 */
export interface Series {
  label: string;
  values: number[];
  color: string;
}

interface Props {
  series: Series[];
  height?: number;
  /** Fixed domain: these are percentages, so the axis should not rescale. */
  max?: number;
}

const PAD = { top: 8, right: 44, bottom: 14, left: 4 };

export function Sparkline({ series, height = 96, max = 100 }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  const width = 300;

  const points = Math.max(...series.map((s) => s.values.length), 0);
  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;

  const x = (i: number) => PAD.left + (points <= 1 ? innerW : (i / (points - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - (Math.min(Math.max(v, 0), max) / max) * innerH;

  const paths = useMemo(
    () =>
      series.map((s) => ({
        ...s,
        d: s.values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" "),
        last: s.values.at(-1),
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [series, points, height, max],
  );

  if (points < 2) {
    return (
      <div
        className="grid place-items-center text-xs text-muted"
        style={{ height }}
      >
        gathering readings…
      </div>
    );
  }

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    const ratio = (event.clientX - box.left) / box.width;
    const index = Math.round(ratio * (points - 1) - PAD.left / innerW);
    setHover(Math.min(Math.max(index, 0), points - 1));
  };

  return (
    <div className="relative">
      <svg
        ref={ref}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="w-full touch-none"
        style={{ height }}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
        role="img"
        aria-label={series.map((s) => `${s.label} ${s.values.at(-1)?.toFixed(0)}%`).join(", ")}
      >
        {/* Recessive gridlines at quarter marks; the data is the ink here. */}
        {[0, 25, 50, 75, 100].map((tick) => (
          <line
            key={tick}
            x1={PAD.left}
            x2={PAD.left + innerW}
            y1={y(tick)}
            y2={y(tick)}
            stroke="var(--color-grid)"
            strokeWidth={tick === 100 || tick === 0 ? 1 : 0.5}
          />
        ))}

        {hover !== null && (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD.top}
            y2={PAD.top + innerH}
            stroke="var(--color-muted)"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
        )}

        {paths.map((p) => (
          <g key={p.label}>
            <path d={p.d} fill="none" stroke={p.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            {p.last !== undefined && (
              <>
                {/* A 2px surface ring keeps the end markers legible where the
                    two lines cross each other. */}
                <circle
                  cx={x(p.values.length - 1)}
                  cy={y(p.last)}
                  r={4}
                  fill={p.color}
                  stroke="var(--color-surface)"
                  strokeWidth={2}
                />
                <text
                  x={PAD.left + innerW + 8}
                  y={y(p.last) + 4}
                  fill={p.color}
                  fontSize={11}
                  fontWeight={600}
                >
                  {p.last.toFixed(0)}%
                </text>
              </>
            )}
            {hover !== null && p.values[hover] !== undefined && (
              <circle
                cx={x(hover)}
                cy={y(p.values[hover]!)}
                r={3.5}
                fill={p.color}
                stroke="var(--color-surface)"
                strokeWidth={2}
              />
            )}
          </g>
        ))}
      </svg>

      {hover !== null && (
        <div className="pointer-events-none absolute left-2 top-1 rounded border border-hairline bg-sunken/95 px-2 py-1 text-[11px] shadow-lg">
          {series.map((s) => (
            <div key={s.label} className="flex items-center gap-1.5 whitespace-nowrap">
              <span aria-hidden className="size-1.5 rounded-full" style={{ background: s.color }} />
              <span className="text-ink-2">{s.label}</span>
              <span className="ml-auto pl-2 font-mono text-ink tabular-nums">
                {s.values[hover]?.toFixed(0) ?? "n/a"}%
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Legend is always present for two or more series: identity never rests
          on colour alone. */}
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        {series.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
            <span aria-hidden className="h-0.5 w-3 rounded" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
