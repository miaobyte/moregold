import { useState, useCallback, useRef } from 'react';
import { type IChartApi, type ISeriesApi, ColorType } from 'lightweight-charts';
import { COLORS } from '../utils/constants';
import { fetchAround } from '../utils/api';

function makeSeries(chart: IChartApi, color: string) {
  return chart.addLineSeries({
    color, lineWidth: 1.5, lineStyle: 2,
    priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
}

function applyOffset(o: Overlay): PricePoint[] {
  if (!o.data) return [];
  return o.data.map(p => ({ ...p, time: (p.time as number) + (o.timeShift || 0), value: p.value + (o.offset || 0) }));
}

function formatDate(ts: number) {
  const d = new Date(ts * 1000);
  return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

function dayOffset(dt: string) {
  const d = new Date(dt); d.setHours(0,0,0,0);
  const t = new Date(); t.setHours(0,0,0,0);
  return Math.round((t.getTime() - d.getTime()) / 86400000);
}

export function useOverlays(chart: IChartApi | null, mode: PriceMode, onUpdate: () => void) {
  const [overlays, setOverlays] = useState<Overlay[]>([]);

  const add = useCallback(async (dt: string, window: number) => {
    const color = COLORS[overlays.length % COLORS.length];
    const o: Overlay = { dt, window, color, label: dt.slice(0,16), series: null, offset: 0, timeShift: 0, data: null };
    setOverlays(prev => [...prev, o]);
    await load(o, overlays.length);
  }, [overlays.length, mode]);

  const load = useCallback(async (o: Overlay, idx?: number) => {
    if (!chart) return;
    const rows = await fetchAround(o.dt, o.window, 5);
    if (!rows.length) return;
    const off = dayOffset(o.dt);
    o.data = rows.map(r => {
      const d = new Date(r.dt); d.setDate(d.getDate() + off);
      return { time: Math.floor(d.getTime()/1000) as Time, value: r[mode], usd: r.usd, cny: r.cny, origTime: d.getTime()/1000 };
    });
    if (o.series) chart.removeSeries(o.series);
    o.series = makeSeries(chart, o.color);
    o.series.setData(applyOffset(o));
    onUpdate();
    setOverlays(prev => [...prev]);
  }, [chart, mode, onUpdate]);

  const remove = useCallback((i: number) => {
    setOverlays(prev => {
      const o = prev[i];
      if (o.series) chart?.removeSeries(o.series);
      return prev.filter((_, j) => j !== i);
    });
  }, [chart]);

  const reload = useCallback(async (o: Overlay, gran: number) => {
    if (!chart || !o.series) return;
    const rows = await fetchAround(o.dt, o.window, gran);
    if (!rows.length) return;
    const off = dayOffset(o.dt);
    o.data = rows.map(r => {
      const d = new Date(r.dt); d.setDate(d.getDate() + off);
      return { time: Math.floor(d.getTime()/1000) as Time, value: r[mode], usd: r.usd, cny: r.cny, origTime: d.getTime()/1000 };
    });
    o.series.setData(applyOffset(o));
    onUpdate();
    setOverlays(prev => [...prev]);
  }, [chart, mode, onUpdate]);

  return { overlays, setOverlays, add, remove, reload, applyOffset, formatDate, dayOffset };
}
