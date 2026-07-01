interface Props {
  lines: { name: string; usd: string; cny: string; time: string; color: string }[];
}

export function Tooltip({ lines }: Props) {
  if (!lines.length) return null;
  return (
    <div className="tooltip">
      <div className="tooltip-grid">
        <div className="tooltip-hd">日期</div>
        <div className="tooltip-hd tooltip-v">USD</div>
        <div className="tooltip-hd tooltip-v">CNY</div>
        {lines.map((l, i) => [
          <div key={`n${i}`}><span style={{color:l.color}}>●</span> <b>{l.name}</b> {l.time}</div>,
          <div key={`u${i}`} className="tooltip-v">{l.usd}</div>,
          <div key={`c${i}`} className="tooltip-v">{l.cny}</div>,
        ]).flat()}
      </div>
    </div>
  );
}
