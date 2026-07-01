import { useRef } from 'react';
import { GRAN_OPTIONS, RANGE_OPTIONS } from '../utils/constants';
import type { Granularity } from '../types';

interface Props {
  onAdd: (dt: string, w: number) => void;
  onYMode: (m: 'usd'|'cny') => void;
  onRange: (h: number) => void;
  onGran: (g: Granularity|0) => void;
}

export function Controls({ onAdd, onYMode, onRange, onGran }: Props) {
  const dateRef = useRef<HTMLInputElement>(null);
  const timeRef = useRef<HTMLInputElement>(null);
  const winRef = useRef<HTMLInputElement>(null);

  const handleAdd = () => {
    const d = dateRef.current?.value;
    if (!d) return;
    const t = timeRef.current?.value;
    const dt = t ? `${d} ${t}:00` : `${d} 00:00:00`;
    const w = parseInt(winRef.current?.value || '24');
    onAdd(dt, w);
  };

  return (
    <div className="controls">
      <label>⏱ 对比</label>
      <input type="date" ref={dateRef} />
      <input type="time" ref={timeRef} step={60} />
      <label>±</label>
      <input type="number" ref={winRef} defaultValue={24} min={1} max={168} />h
      <button className="ctr-btn" onClick={handleAdd}>+ 添加</button>
      <YMode onChange={onYMode} />
      <label>范围</label>
      <select onChange={e => onRange(parseInt(e.target.value))} defaultValue="24">
        {RANGE_OPTIONS.map(([v,l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <label>K线</label>
      <select onChange={e => onGran(parseInt(e.target.value) as Granularity|0)} defaultValue="auto">
        {GRAN_OPTIONS.map(([v,l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

function YMode({ onChange }: { onChange: (m: 'usd'|'cny') => void }) {
  return (
    <>
      <label style={{marginLeft:8}}>Y轴</label>
      <select onChange={e => onChange(e.target.value as 'usd'|'cny')}>
        <option value="usd">USD/oz</option><option value="cny">CNY/g</option>
      </select>
    </>
  );
}
