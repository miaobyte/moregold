import type { Overlay } from '../types';

interface Props {
  overlays: Overlay[];
  onRemove: (i: number) => void;
}

export function OverlayTags({ overlays, onRemove }: Props) {
  if (!overlays.length) return null;
  return (
    <div className="overlay-bar">
      {overlays.map((o, i) => {
        const info = [];
        if (o.timeShift) info.push(`Δt${(o.timeShift>=0?'+':'')}${(o.timeShift/3600).toFixed(1)}h`);
        if (o.offset) info.push(`${(o.offset>=0?'+':'')}${o.offset.toFixed(1)}`);
        return (
          <div key={i} className="ov-tag" style={{borderLeft:`3px solid ${o.color}`}}>
            <span className="ov-dot" style={{background:o.color}} />
            {o.label} ±{o.window}h
            {info.length ? <span style={{color:'#f0c040'}}>{info.join(' ')}</span> : null}
            <button className="ov-rm" onClick={() => onRemove(i)}>×</button>
          </div>
        );
      })}
    </div>
  );
}
