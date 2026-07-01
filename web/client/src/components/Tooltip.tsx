import type { Overlay } from '../types';

interface Props {
  lines: { name: string; usd: string; cny: string; time: string; color: string }[];
}

export function Tooltip({ lines }: Props) {
  if (!lines.length) return null;
  return (
    <div style={{position:'fixed',top:42,right:12,background:'rgba(30,34,45,0.93)',border:'1px solid #3a3e4a',borderRadius:4,padding:'6px 10px',fontSize:12,zIndex:1000,pointerEvents:'none',boxShadow:'0 2px 10px rgba(0,0,0,0.6)',fontFamily:'monospace'}}>
      <div style={{display:'grid',gridTemplateColumns:'auto 72px 72px',columnGap:10,rowGap:1,alignItems:'center'}}>
        <div style={{color:'#787b86',fontSize:10,borderBottom:'1px solid #3a3e4a',paddingBottom:2}}>日期</div>
        <div style={{color:'#787b86',fontSize:10,borderBottom:'1px solid #3a3e4a',paddingBottom:2,textAlign:'right'}}>USD</div>
        <div style={{color:'#787b86',fontSize:10,borderBottom:'1px solid #3a3e4a',paddingBottom:2,textAlign:'right'}}>CNY</div>
        {lines.map((l, i) => [
          <div key={`n${i}`}><span style={{color:l.color}}>●</span> <b>{l.name}</b> {l.time}</div>,
          <div key={`u${i}`} style={{textAlign:'right'}}>{l.usd}</div>,
          <div key={`c${i}`} style={{textAlign:'right'}}>{l.cny}</div>,
        ]).flat()}
      </div>
    </div>
  );
}
