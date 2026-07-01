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
    <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap',padding:'4px 12px',background:'#1e222d',borderBottom:'1px solid #2a2e39',fontSize:12}}>
      <label style={{color:'#787b86'}}>⏱ 对比</label>
      <input type="date" ref={dateRef} style={inputStyle} />
      <input type="time" ref={timeRef} step={60} style={inputStyle} />
      <label style={{color:'#787b86'}}>±</label>
      <input type="number" ref={winRef} defaultValue={24} min={1} max={168} style={{...inputStyle,width:48}} />h
      <button onClick={handleAdd} style={btnStyle}>+ 添加</button>
      <label style={{color:'#787b86',marginLeft:8}}>Y轴</label>
      <select onChange={e => onYMode(e.target.value as 'usd'|'cny')} style={inputStyle}>
        <option value="usd">USD/oz</option><option value="cny">CNY/g</option>
      </select>
      <label style={{color:'#787b86'}}>范围</label>
      <select onChange={e => onRange(parseInt(e.target.value))} defaultValue="24" style={inputStyle}>
        {RANGE_OPTIONS.map(([v,l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <label style={{color:'#787b86'}}>K线</label>
      <select onChange={e => onGran(parseInt(e.target.value) as Granularity|0)} defaultValue="auto" style={inputStyle}>
        {GRAN_OPTIONS.map(([v,l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

const inputStyle: React.CSSProperties = {background:'#2a2e39',color:'#d1d4dc',border:'1px solid #3a3e4a',padding:'3px 6px',borderRadius:3,fontSize:12};
const btnStyle: React.CSSProperties = {...inputStyle,background:'#1976d2',color:'#fff',cursor:'pointer',border:'none'};
