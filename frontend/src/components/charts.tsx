import { useState, type ReactNode } from "react";

/* Shared chart chrome. Grid and axes are deliberately recessive — they orient
   the eye without competing with the data. */
const GRID = "var(--color-grid)";
const AXIS = "var(--color-axis)";
const MUTED = "var(--color-ink-muted)"; // bound to the token, never hardcoded

function Tooltip({
  x,
  y,
  children,
}: {
  x: number | string;
  y: number | string;
  children: ReactNode;
}) {
  return (
    <div
      className="pointer-events-none absolute z-20 rounded-lg border border-line bg-overlay px-2.5 py-1.5 text-[12px] whitespace-nowrap shadow-[var(--shadow-pop)]"
      style={{
        left: x,
        top: y,
        transform: "translate(-50%, calc(-100% - 9px))",
      }}
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ bars */

export function BarChart({
  data,
  height = 168,
  color = "var(--color-series-1)",
  valueFormat = (v: number) => String(v),
  xLabelEvery = 1,
}: {
  data: { label: string; value: number; sublabel?: string }[];
  height?: number;
  color?: string;
  valueFormat?: (v: number) => string;
  xLabelEvery?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!data.length) return null;

  const max = Math.max(...data.map((d) => d.value)) || 1;
  const plotH = height - 24;
  // 2px gap between adjacent bars, per the mark spec.
  const slot = 100 / data.length;

  return (
    <div className="relative w-full" style={{ height }}>
      <svg width="100%" height={height} className="overflow-visible">
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line
            key={f}
            x1="0"
            x2="100%"
            y1={plotH - plotH * f}
            y2={plotH - plotH * f}
            stroke={GRID}
            strokeWidth="1"
          />
        ))}
        <line x1="0" x2="100%" y1={plotH} y2={plotH} stroke={AXIS} strokeWidth="1" />

        {data.map((d, i) => {
          const h = Math.max(2, (d.value / max) * plotH);
          const isHover = hover === i;
          return (
            <g key={i}>
              <rect
                x={`${i * slot}%`}
                y={0}
                width={`${slot}%`}
                height={plotH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "pointer" }}
              />
              <rect
                x={`calc(${i * slot}% + 1px)`}
                y={plotH - h}
                width={`calc(${slot}% - 2px)`}
                height={h}
                rx={4}
                fill={color}
                opacity={hover === null || isHover ? 1 : 0.45}
                style={{ transition: "opacity 140ms ease", pointerEvents: "none" }}
              />
            </g>
          );
        })}

        {data.map((d, i) =>
          i % xLabelEvery === 0 ? (
            <text
              key={i}
              x={`${i * slot + slot / 2}%`}
              y={height - 6}
              textAnchor="middle"
              fill={MUTED}
              fontSize="10"
              className="tnum"
            >
              {d.label}
            </text>
          ) : null,
        )}
      </svg>

      {hover !== null && (
        <Tooltip x={`${(hover + 0.5) * slot}%`} y={plotH - (data[hover].value / max) * plotH}>
          <span className="text-ink font-medium">{valueFormat(data[hover].value)}</span>
          <span className="text-ink-muted ml-1.5">
            {data[hover].sublabel ?? data[hover].label}
          </span>
        </Tooltip>
      )}
    </div>
  );
}

/* ------------------------------------------------------- horizontal bars */

export function HBarChart({
  data,
  valueFormat = (v: number) => String(v),
  color = "var(--color-series-1)",
  maxRows = 10,
}: {
  data: { label: string; value: number; meta?: string }[];
  valueFormat?: (v: number) => string;
  color?: string;
  maxRows?: number;
}) {
  const rows = data.slice(0, maxRows);
  const max = Math.max(...rows.map((d) => d.value)) || 1;

  return (
    <div className="space-y-2">
      {rows.map((d) => (
        <div key={d.label} className="group">
          <div className="flex items-baseline justify-between gap-3 mb-1">
            <span className="text-[13px] font-medium text-ink-secondary truncate">{d.label}</span>
            <span className="tnum text-[12.5px] text-ink shrink-0">
              {valueFormat(d.value)}
              {d.meta && <span className="text-ink-muted ml-2 font-sans">{d.meta}</span>}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-track overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.max(1.5, (d.value / max) * 100)}%`,
                backgroundColor: color,
                transition: "width 700ms cubic-bezier(0.16,1,0.3,1)",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ line */

/** Line/area chart.
 *
 *  A `null` value is a genuine data gap and the line BREAKS across it. Silently
 *  interpolating over missing periods would assert continuity the data does not
 *  support — a data-integrity failure on a product about trustworthy data
 *  (dashboard.md §9).
 */
export function LineChart({
  data,
  height = 180,
  color = "var(--color-series-1)",
  valueFormat = (v: number) => String(v),
  gapNote,
}: {
  data: { label: string | number; value: number | null }[];
  height?: number;
  color?: string;
  valueFormat?: (v: number) => string;
  gapNote?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (data.length < 2) return null;

  const W = 100;
  const plotH = height - 24;
  const values = data.map((d) => d.value).filter((v): v is number => v !== null);
  const max = Math.max(...values) || 1;
  const min = 0;
  const px = (i: number) => (i / (data.length - 1)) * W;
  const py = (v: number) => plotH - ((v - min) / (max - min)) * plotH;

  // Split into contiguous runs so a null produces a real break, not a bridge.
  const segments: { i: number; value: number }[][] = [];
  let run: { i: number; value: number }[] = [];
  data.forEach((d, i) => {
    if (d.value === null) {
      if (run.length) segments.push(run);
      run = [];
    } else {
      run.push({ i, value: d.value });
    }
  });
  if (run.length) segments.push(run);

  const line = segments
    .map((seg) => seg.map((p, k) => `${k === 0 ? "M" : "L"}${px(p.i)},${py(p.value)}`).join(" "))
    .join(" ");
  const area = segments
    .filter((seg) => seg.length > 1)
    .map((seg) => {
      const path = seg.map((p, k) => `${k === 0 ? "M" : "L"}${px(p.i)},${py(p.value)}`).join(" ");
      return `${path} L${px(seg[seg.length - 1].i)},${plotH} L${px(seg[0].i)},${plotH} Z`;
    })
    .join(" ");

  return (
    <div className="relative w-full" style={{ height }}>
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        className="overflow-visible"
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="lineFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.16" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>

        {[0.33, 0.66, 1].map((f) => (
          <line
            key={f}
            x1="0"
            x2={W}
            y1={plotH - plotH * f}
            y2={plotH - plotH * f}
            stroke={GRID}
            strokeWidth="0.4"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        <path d={area} fill="url(#lineFill)" />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {hover !== null && (
          <>
            <line
              x1={px(hover)}
              x2={px(hover)}
              y1="0"
              y2={plotH}
              stroke={AXIS}
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
          </>
        )}

        {data.map((_, i) => (
          <rect
            key={i}
            x={px(i) - W / data.length / 2}
            y={0}
            width={W / data.length}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            style={{ cursor: "pointer" }}
          />
        ))}
      </svg>

      {/* Point markers are HTML, not SVG: the plot stretches non-uniformly
          (preserveAspectRatio="none"), which would turn circles into smears. */}
      {segments
        .filter((seg) => seg.length === 1)
        .map((seg) => (
          <span
            key={`pt-${seg[0].i}`}
            aria-hidden
            className="pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full"
            style={{ left: `${(px(seg[0].i) / W) * 100}%`, top: py(seg[0].value), backgroundColor: color }}
          />
        ))}
      {hover !== null && data[hover].value !== null && (
        <span
          aria-hidden
          className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
          style={{
            left: `${(px(hover) / W) * 100}%`,
            top: py(data[hover].value as number),
            backgroundColor: color,
            boxShadow: "0 0 0 1px var(--color-line-strong)",
          }}
        />
      )}

      <div className="absolute inset-x-0 flex justify-between px-0" style={{ top: plotH + 6 }}>
        {data.map((d, i) =>
          i % Math.ceil(data.length / 7) === 0 ? (
            <span key={i} className="tnum text-[10px]" style={{ color: MUTED }}>
              {d.label}
            </span>
          ) : (
            <span key={i} />
          ),
        )}
      </div>

      {gapNote && (
        <div className="absolute inset-x-0 -bottom-4 text-[10px] text-ink-muted">{gapNote}</div>
      )}

      {hover !== null && (
        <Tooltip
          x={`${(px(hover) / W) * 100}%`}
          y={data[hover].value === null ? plotH / 2 : py(data[hover].value as number)}
        >
          <span className="text-ink font-medium">
            {data[hover].value === null ? "No data" : valueFormat(data[hover].value as number)}
          </span>
          <span className="text-ink-muted ml-1.5">{data[hover].label}</span>
        </Tooltip>
      )}
    </div>
  );
}

/* ------------------------------------------------- attribution (diverging) */

/** Feature contributions. Diverging by sign: one hue each way, no midpoint hue.
 *  Every row is directly labelled, so colour is pure reinforcement. */
export function AttributionBars({
  items,
}: {
  items: { label: string; contribution: number; feature: string }[];
}) {
  if (!items.length) return null;
  // A zero contribution is a summary line, not a measurement: the model's
  // headline prediction, already split across the bars below it.
  const summary = items.filter((i) => i.contribution === 0);
  const bars = items.filter((i) => i.contribution !== 0);
  const max = Math.max(...bars.map((i) => Math.abs(i.contribution))) || 1;

  return (
    <div className="space-y-3">
      {summary.map((it, i) => (
        <p key={`s${i}`} className="text-[12.5px] leading-snug text-ink-muted">
          {it.label}
        </p>
      ))}
      {bars.map((it, i) => {
        const positive = it.contribution >= 0;
        const width = (Math.abs(it.contribution) / max) * 50;
        return (
          <div key={i}>
            <div className="flex items-start justify-between gap-3 mb-1.5">
              <span className="text-[12.5px] text-ink-secondary leading-snug">{it.label}</span>
              <span
                className="tnum text-[12px] shrink-0 font-medium"
                style={{
                  color: positive ? "var(--color-good)" : "var(--color-critical)",
                }}
              >
                {positive ? "+" : ""}
                {it.contribution.toFixed(1)}
              </span>
            </div>
            <div className="relative h-1.5 w-full rounded-full bg-track">
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-axis" />
              <div
                className="absolute top-0 h-full rounded-full"
                style={{
                  width: `${Math.max(1, width)}%`,
                  [positive ? "left" : "right"]: "50%",
                  backgroundColor: positive ? "var(--color-good)" : "var(--color-critical)",
                  transition: "width 600ms cubic-bezier(0.16,1,0.3,1)",
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* --------------------------------------------------------------- sparkline */

export function Sparkline({
  values,
  width = 68,
  height = 22,
  color = "var(--color-series-1)",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * width},${height - ((v - min) / range) * height}`)
    .join(" ");
  return (
    <svg width={width} height={height} className="shrink-0">
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
