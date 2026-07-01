interface Props {
  lines: { name: string; usd: string; cny: string; time: string; color: string }[];
}

export function InfoPanel({ lines }: Props) {
  if (!lines.length) return null;
  return (
    <div className="info-panel">
      <div className="info-grid">
        <div className="info-hd">名称</div>
        <div className="info-hd info-v">USD</div>
        <div className="info-hd info-v">CNY</div>
        {lines.map((l, i) => [
          <div key={`n${i}`}><span style={{color:l.color}}>●</span> <b>{l.name}</b> {l.time}</div>,
          <div key={`u${i}`} className="info-v">{l.usd}</div>,
          <div key={`c${i}`} className="info-v">{l.cny}</div>,
        ]).flat()}
      </div>
    </div>
  );
}
