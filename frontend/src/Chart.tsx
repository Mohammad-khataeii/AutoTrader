import React from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { type Row } from "./api";
import { date, money, number } from "./model";
import { Panel } from "./ui";
export function EquityChart({
  rows,
  title = "Equity",
  caption,
}: {
  rows: Row[];
  title?: string;
  caption?: string;
}) {
  const data = [...rows]
    .filter(
      (r) =>
        !r.degraded &&
        number(r.equity) != null &&
        Number.isFinite(new Date(r.timestamp ?? r.time).getTime()),
    )
    .sort(
      (a, b) =>
        new Date(a.timestamp ?? a.time).getTime() -
        new Date(b.timestamp ?? b.time).getTime(),
    )
    .map((r) => ({
      ...r,
      equity: Number(r.equity),
      time: date(r.timestamp ?? r.time, true),
    }));
  return (
    <Panel className="equity-panel">
      <div className="section-heading">
        <h2>{title}</h2>
        {caption && <span className="muted small">{caption}</span>}
      </div>
      {data.length > 1 && data.some((r) => r.equity !== data[0].equity) ? (
        <div
          className="equity-chart"
          role="img"
          aria-label={`${title}: ${data.length} recorded observations`}
        >
          <ResponsiveContainer width="100%" height={235}>
            <AreaChart
              data={data}
              margin={{ top: 15, right: 8, left: 0, bottom: 0 }}
            >
              <XAxis dataKey="time" hide />
              <YAxis
                width={64}
                domain={["auto", "auto"]}
                tickFormatter={(v) => `€${v}`}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 11, fill: "#6b7771" }}
              />
              <Tooltip
                formatter={(v: number) => [money(v), "Virtual equity"]}
              />
              <Area
                dataKey="equity"
                stroke="#217454"
                strokeWidth={2}
                fill="#edf6f0"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="chart-empty">
          {data.length > 1
            ? `Equity unchanged across ${data.length} recorded observations.`
            : "Equity history will appear after two valid recorded observations."}
        </div>
      )}
    </Panel>
  );
}
