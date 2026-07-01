import { useState, useRef, useCallback, useEffect } from 'react';
import { createChart, ColorType, type IChartApi, type ISeriesApi, type Time } from 'lightweight-charts';
import { Controls } from './components/Controls';
import { OverlayTags } from './components/OverlayTags';
import { Tooltip } from './components/Tooltip';
import { useSSE } from './hooks/useSSE';
import { fetchRecent } from './utils/api';
import { MAIN_COLOR, getGranularity } from './utils/constants';
import type { Overlay, Granularity, PricePoint } from './types';
import './App.css';

export default function App() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainRef = useRef<ISeriesApi<'Line'> | null>(null);
  const cnyRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [price, setPrice] = useState({ usd: '—', cny: '—' });
  const [overlays, setOverlays] = useState<Overlay[]>([]);
  const [gran, setGran] = useState<Granularity>(1);
  const [manualGran, setManualGran] = useState<Granularity | 0>(0);
  const [tooltipLines, setTooltipLines] = useState<any[]>([]);
  const dragRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const c = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#131722' }, textColor: '#787b86' },
      grid: { vertLines: { color: '#1e222d' }, horzLines: { color: '#1e222d' } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#4fc3f7', scaleMargins: { top: 0.05, bottom: 0.05 } },
      leftPriceScale: { borderColor: '#81c784', visible: true, scaleMargins: { top: 0.05, bottom: 0.05 } },
      timeScale: { borderColor: '#2a2e39', timeVisible: true, secondsVisible: false },
      handleScroll: { vertTouchDrag: true, horzTouchDrag: true, mouseWheel: true },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });
    chartRef.current = c;

    c.timeScale().subscribeVisibleTimeRangeChange(async (range) => {
      if (!range?.from || !range?.to || manualGran) return;
      const span = range.to - range.from;
      if (span < 300 || span > 365 * 86400) return;
      const g = getGranularity(span);
      if (g === gran) return;
      setGran(g);
    });

    c.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData || dragRef.current) { setTooltipLines([]); return; }
      const lines: any[] = [];
      const fmt = (ts: number) => {
        const d = new Date(ts * 1000);
        return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
      };
      const mv = param.seriesData.get(mainRef.current!);
      if (mv != null) {
        const v = (mv as any).value ?? (mv as any).close;
        const cv = param.seriesData.get(cnyRef.current!);
        const cnyVal = cv != null ? (cv as any).value ?? (cv as any).close : (v * 7.0 / 31.1035);
        lines.push({ name: '实时', usd: v?.toFixed(1) || '—', cny: cnyVal?.toFixed(2) || '—', time: fmt(param.time as number), color: MAIN_COLOR });
      }
      setTooltipLines(lines);
    });

    return () => { c.remove(); chartRef.current = null; };
  }, []);

  const loadMain = useCallback(async (g: Granularity) => {
    const rows = await fetchRecent(24, g);
    if (!rows.length) return;
    const usdData: PricePoint[] = rows.map(r => ({
      time: Math.floor(new Date(r.dt).getTime() / 1000) as Time,
      value: r.usd, usd: r.usd, cny: r.cny,
    }));
    const cnyData: PricePoint[] = rows.map(r => ({
      time: Math.floor(new Date(r.dt).getTime() / 1000) as Time,
      value: r.cny || (r.usd * 7.0 / 31.1035), usd: r.usd, cny: r.cny,
    }));
    if (!mainRef.current && chartRef.current) {
      mainRef.current = chartRef.current.addLineSeries({ color: MAIN_COLOR, lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
      cnyRef.current = chartRef.current.addLineSeries({ color: '#81c784', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, priceScaleId: 'left', visible: false });
    }
    mainRef.current?.setData(usdData);
    cnyRef.current?.setData(cnyData);
    chartRef.current?.timeScale().fitContent();
    const last = rows[rows.length - 1];
    setPrice({ usd: last.usd?.toFixed(1) || '—', cny: last.cny?.toFixed(2) || '—' });
  }, []);

  useEffect(() => { loadMain(gran); }, [gran]);

  useSSE((d) => {
    const ts = Math.floor(new Date(d.dt).getTime() / 1000) as Time;
    mainRef.current?.update({ time: ts, value: d.usd });
    cnyRef.current?.update({ time: ts, value: d.cny || (d.usd * 7.0 / 31.1035) });
    setPrice({ usd: d.usd.toFixed(1), cny: d.cny.toFixed(2) });
  });

  const addOverlay = useCallback(async (dt: string, w: number) => {
    const c = chartRef.current;
    if (!c) return;
    const COLORS = ['#ff7043','#81c784','#ba68c8','#ffd54f','#4dd0e1','#f06292','#aed581','#ff8a65','#90a4ae'];
    const color = COLORS[overlays.length % COLORS.length];
    const o: Overlay = { dt, window: w, color, label: dt.slice(0,16), series: null, offset: 0, timeShift: 0, data: null };
    const off = (() => { const d2 = new Date(dt); d2.setHours(0,0,0,0); const t2 = new Date(); t2.setHours(0,0,0,0); return Math.round((t2.getTime() - d2.getTime()) / 86400000); })();
    const r = await fetch(`/api/around?dt=${encodeURIComponent(dt)}&hours=${w}&granularity=5`).then(r => r.json());
    if (!r.length) return;
    o.data = r.map((rx: any) => {
      const d3 = new Date(rx.dt); d3.setDate(d3.getDate() + off);
      return { time: Math.floor(d3.getTime()/1000) as Time, value: rx.usd, usd: rx.usd, cny: rx.cny, origTime: d3.getTime()/1000 };
    });
    o.series = c.addLineSeries({ color, lineWidth: 1.5, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
    o.series.setData(o.data.map(p => ({ time: (p.time as number) + (o.timeShift||0), value: p.value + (o.offset||0) })));
    setOverlays(prev => [...prev, o]);
  }, [overlays.length]);

  const removeOverlay = useCallback((i: number) => {
    setOverlays(prev => {
      const o = prev[i];
      if (o.series) chartRef.current?.removeSeries(o.series);
      return prev.filter((_, j) => j !== i);
    });
  }, []);

  return (
    <>
      <div className="topbar">
        <h1>🥇 GoldView</h1>
        <div className="prices">
          <span>💰 <span className="v" style={{color:'#4fc3f7'}}>{price.usd}</span> USD (右轴)</span>
          <span>💴 <span className="v" style={{color:'#81c784'}}>{price.cny}</span> CNY (左轴)</span>
        </div>
      </div>
      <Controls onAdd={addOverlay} onRange={h => chartRef.current?.timeScale().setVisibleRange({from: Date.now()/1000 - h*3600, to: Date.now()/1000})} onGran={g => { setManualGran(g as any); if (g) setGran(g as Granularity); }} />
      <OverlayTags overlays={overlays} onRemove={removeOverlay} />
      <div className="chart-area" ref={containerRef} />
      <Tooltip lines={tooltipLines} />
    </>
  );
}
