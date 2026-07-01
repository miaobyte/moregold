import { useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { GRAN_OPTIONS, RANGE_OPTIONS } from '@/utils/constants';
import type { Granularity } from '@/types';

interface Props {
  onAdd: (dt: string, w: number) => void;
  onRange: (h: number) => void;
  onGran: (g: Granularity | 0) => void;
}

export function Controls({ onAdd, onRange, onGran }: Props) {
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
    <div className="flex gap-2 items-center flex-wrap px-3 py-1 bg-panel border-b border-border text-xs">
      <span className="text-muted">⏱ 对比</span>
      <Input type="date" ref={dateRef} className="w-[130px]" />
      <Input type="time" ref={timeRef} step={60} className="w-[110px]" />
      <span>±</span>
      <Input type="number" ref={winRef} defaultValue={24} min={1} max={168} className="w-14" />
      <span>h</span>
      <Button size="sm" onClick={handleAdd}>+ 添加</Button>

      <span className="text-muted ml-2">范围</span>
      <Select defaultValue="24" onValueChange={v => onRange(parseInt(v))}>
        <SelectTrigger className="w-[72px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {RANGE_OPTIONS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
        </SelectContent>
      </Select>

      <span className="text-muted">K线</span>
      <Select defaultValue="auto" onValueChange={v => onGran(parseInt(v) as Granularity | 0)}>
        <SelectTrigger className="w-[72px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {GRAN_OPTIONS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>
  );
}
