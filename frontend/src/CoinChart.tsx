import React, { useEffect, useId, useRef, useState } from "react";
import { type Row, useResource } from "./api";
import { date, number, price } from "./model";
import { Empty, ResourceState } from "./ui";

export function validCandles(rows: Row[]): Row[] {
  return rows.filter(r => Number.isFinite(new Date(r.timestamp).getTime()) &&
    [r.open, r.high, r.low, r.close].every(v => number(v) != null && Number(v) > 0))
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
}

export function CoinChart({ symbol }: { symbol: string }) {
  const [range, setRange] = useState("6h");
  const [style, setStyle] = useState("candles");
  const [hover, setHover] = useState<number | null>(null);
  const chartElement = useRef<SVGSVGElement>(null);
  const [chartWidth, setChartWidth] = useState(900);
  const gradient = useId().replace(/:/g, "");
  const resource = useResource(`/api/personal-paper/markets/${encodeURIComponent(symbol)}/chart?range=${range}`, {poll: 30000});
  useEffect(() => {
    const element = chartElement.current;
    if (!element) return;
    const observer = new ResizeObserver(entries => setChartWidth(Math.max(280, entries[0].contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [resource.data]);
  const plotWidth = chartWidth - 110;
  const rows = validCandles(resource.data?.candles ?? []);
  const last = rows[rows.length - 1];
  const focused = rows[hover ?? rows.length - 1] ?? last;
  const change = last && rows[0] ? (Number(last.close) / Number(rows[0].open) - 1) * 100 : null;
  const times = rows.map(r => new Date(r.timestamp).getTime());
  const start = times[0], finish = times[times.length - 1];
  const low = Math.min(...rows.map(r => Number(r.low))), high = Math.max(...rows.map(r => Number(r.high)));
  const pad = Math.max((high - low) * .1, high * .0002);
  const x = (i: number) => 10 + (times[i] - start) / Math.max(finish - start, 300000) * plotWidth;
  const y = (p: number) => 22 + (high + pad - p) / (high - low + pad * 2) * 235;
  const width = Math.max(1.2, Math.min(10, plotWidth / Math.max((finish - start) / 300000 + 1, 1) * .62));
  const line = rows.map((r, i) => `${i === 0 || times[i] - times[i-1] > 301000 ? "M" : "L"}${x(i)},${y(Number(r.close))}`).join(" ");
  return <div className="coin-chart" aria-label={`${symbol} chart`}>
    <div className="coin-chart-heading"><div><p className="eyebrow">{symbol.split("-")[0]} / Euro · market history</p><h2>{symbol}</h2><strong className="coin-chart-price">{last ? price(last.close) : "Price unavailable"}</strong>
      {change != null && <span className={`coin-change ${change >= 0 ? "gain" : "loss"}`}>{change >= 0 ? "+" : ""}{change.toFixed(2)}% <span>in recorded window</span></span>}</div>
      <div className="chart-options"><div role="group" aria-label="Chart range">{["1h", "6h", "24h"].map(r => <button key={r} aria-pressed={range === r} onClick={() => {setRange(r);setHover(null);}}>{r.toUpperCase()}</button>)}</div>
        <div role="group" aria-label="Chart style">{["candles", "line"].map(s => <button key={s} aria-pressed={style === s} onClick={() => setStyle(s)}>{s === "candles" ? "Candles" : "Line"}</button>)}</div></div>
    </div>
    <ResourceState resource={resource} label="Coin history"/>
    {rows.length > 0 ? <>
      <div className="chart-ohlc" aria-live="off"><span>{date(focused.timestamp, true)}</span><span>O <b>{price(focused.open)}</b></span><span>H <b>{price(focused.high)}</b></span><span>L <b>{price(focused.low)}</b></span><span>C <b>{price(focused.close)}</b></span></div>
      <svg ref={chartElement} viewBox={`0 0 ${chartWidth} 300`} role="img" aria-label={`${symbol}: ${rows.length} recorded five-minute ${style === "candles" ? "candles" : "closing prices"}`} className="price-chart-svg"
        tabIndex={0} onMouseLeave={() => setHover(null)} onKeyDown={e => {if(e.key === "ArrowLeft" || e.key === "ArrowRight") {e.preventDefault();setHover(Math.max(0, Math.min(rows.length - 1, (hover ?? rows.length-1) + (e.key === "ArrowLeft" ? -1 : 1))));}}}
        onMouseMove={e => {const rect=e.currentTarget.getBoundingClientRect();const target=(e.clientX-rect.left)/rect.width*chartWidth;setHover(rows.reduce((best, _r, i) => Math.abs(x(i)-target)<Math.abs(x(best)-target) ? i : best, 0));}}>
        <defs><linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6ca88e" stopOpacity=".22"/><stop offset="100%" stopColor="#6ca88e" stopOpacity="0"/></linearGradient></defs>
        {[0, 1, 2, 3].map(i => {const v=low-pad+(high-low+pad*2)*i/3;return <g key={i}><line x1="10" x2={plotWidth+10} y1={y(v)} y2={y(v)} stroke="#e7eee8" strokeDasharray="3 5"/><text x={plotWidth+25} y={y(v)+4} fill="#758178" fontSize="11">{price(v)}</text></g>;})}
        {style === "line" ? <path d={line} fill="none" stroke="#2b8867" strokeWidth="2.3"/> : rows.map((r, i) => <g key={r.timestamp}>
          <line x1={x(i)} x2={x(i)} y1={y(Number(r.high))} y2={y(Number(r.low))} stroke={Number(r.close)>=Number(r.open) ? "#338665" : "#c96c62"}/>
          <rect x={x(i)-width/2} y={Math.min(y(Number(r.open)),y(Number(r.close)))} width={width} height={Math.max(1,Math.abs(y(Number(r.open))-y(Number(r.close))))} fill={Number(r.close)>=Number(r.open) ? "#338665" : "#c96c62"}/>
        </g>)}
        {hover != null && rows[hover] && <line x1={x(hover)} x2={x(hover)} y1="15" y2="260" stroke="#687b6e" strokeDasharray="4 4"/>}
        {[0, Math.floor((rows.length-1)/2), rows.length-1].filter((v,i,a)=>a.indexOf(v)===i).map(i=><text key={i} x={x(i)} y="288" textAnchor={i===0 ? "start" : i===rows.length-1 ? "end" : "middle"} fill="#758178" fontSize="11">{new Date(rows[i].timestamp).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}</text>)}
      </svg>
      <p className="small muted">5-minute candles · Last candle {date(last.timestamp, true)} · {resource.data?.evidence_category === "SYNTHETIC_ACCEPTANCE" ? "Test fixtures" : "Recorded Revolut X data"}. {resource.data?.missing_intervals > 0 ? `${resource.data.missing_intervals} missing intervals shown as gaps.` : "Closed candles only."} {rows.length < (resource.data?.expected_bars ?? 0) && "Partial recorded window."}</p>
    </> : resource.data ? <Empty title="No recorded candles in this window">The worker has not saved candle history for this coin in the selected range yet. Try a longer range or another coin.</Empty> : null}
  </div>;
}
