import type { Overlay } from '../types';

interface Props {
  overlays: Overlay[];
  onRemove: (i: number) => void;
}

export function OverlayTags({ overlays, onRemove }: Props) {
  if (!overlays.length) return null;
  return (
    <div style={{display:'flex',gap:6,flexWrap:'wrap',padding:'3px 12px',background:'#1e222d',fontSize:11}}>
      {overlays.map((o, i) => {
        const info = [];
        if (o.timeShift) info.push(`Δt${(o.timeShift>=0?'+':'')}${(o.timeShift/3600).toFixed(1)}h`);
        if (o.offset) info.push(`${(o.offset>=0?'+':'')}${o.offset.toFixed(1)}`);
        return (
          <div key={i} style={{display:'flex',alignItems:'center',gap:5,background:'#2a2e39',padding:'2px 7px',borderRadius:3,borderLeft:`3px solid ${o.color}`}}>
            <span style={{width:7,height:7,borderRadius:'50%',background:o.color,cursor:'grab'}} />
            {o.label} ±{o.window}h
            {info.length ? <span style={{color:'#f0c040'}}>{info.join(' ')}</span> : null}
            <button onClick={() => onRemove(i)} style={{background:'#c62828',color:'#fff',border:'none',borderRadius:3,padding:'2px 7px',fontSize:10,cursor:'pointer'}}>×</button>
          </div>
        );
      })}
    </div>
  );
}
