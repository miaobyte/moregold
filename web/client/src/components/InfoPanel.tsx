interface Props {
  lines: { name: string; usd: string; cny: string; time: string; color: string }[];
}

export function InfoPanel({ lines }: Props) {
  if (!lines.length) return null;
  return (
    <div className="info-panel">
      <table style={{borderCollapse:'collapse',fontSize:12}}>
        <thead>
          <tr style={{color:'#787b86',fontSize:10,borderBottom:'1px solid #3a3e4a'}}>
            <th style={{textAlign:'left',padding:'0 8px 2px 0'}}>名称</th>
            <th style={{textAlign:'right',padding:'0 0 2px 8px',width:72}}>USD</th>
            <th style={{textAlign:'right',padding:'0 0 2px 8px',width:72}}>CNY</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td style={{padding:'1px 8px 1px 0',whiteSpace:'nowrap'}}>
                <span style={{color:l.color}}>●</span> <b>{l.name}</b> <span style={{color:'#999',fontSize:11}}>{l.time}</span>
              </td>
              <td style={{textAlign:'right',padding:'1px 0 1px 8px'}}>{l.usd}</td>
              <td style={{textAlign:'right',padding:'1px 0 1px 8px'}}>{l.cny}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
