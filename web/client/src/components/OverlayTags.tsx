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
        return (
          <div key={i} className="ov-tag" style={{borderLeft:`3px solid ${o.color}`}}>
            <span className="ov-dot" style={{background:o.color}} />
            {o.label} ±{o.window}h
            <button className="ov-rm" onClick={() => onRemove(i)}>×</button>
          </div>
        );
      })}
    </div>
  );
}
