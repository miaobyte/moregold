interface Props {
  lines: { name: string; usd: string; cny: string; time: string; color: string }[];
}

export function InfoPanel({ lines }: Props) {
  if (!lines.length) return null;

  return (
    <div className="fixed top-[42px] right-3 z-[1000] rounded border border-[#3a3e4a] bg-panel/95 px-2.5 py-1.5 text-xs font-mono shadow-lg">
      <table className="border-collapse text-xs">
        <thead>
          <tr className="text-[10px] text-muted border-b border-[#3a3e4a]">
            <th className="text-left pr-2 pb-0.5">名称</th>
            <th className="text-right pl-2 pb-0.5 w-[72px]">USD</th>
            <th className="text-right pl-2 pb-0.5 w-[72px]">CNY</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td className="py-px pr-2 whitespace-nowrap">
                <span style={{ color: l.color }}>●</span>{' '}
                <b>{l.name}</b>{' '}
                <span className="text-[#999] text-[11px]">{l.time}</span>
              </td>
              <td className="text-right py-px pl-2">{l.usd}</td>
              <td className="text-right py-px pl-2">{l.cny}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
