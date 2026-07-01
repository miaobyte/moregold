import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { Overlay } from '@/types';

interface Props {
  overlays: Overlay[];
  onRemove: (i: number) => void;
}

export function OverlayTags({ overlays, onRemove }: Props) {
  if (!overlays.length) return null;

  return (
    <div className="flex gap-1.5 flex-wrap px-3 py-1 bg-panel text-[11px]">
      {overlays.map((o, i) => (
        <Badge
          key={i}
          className="gap-1.5 pl-1.5 border-l-[3px]"
          style={{ borderLeftColor: o.color }}
        >
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: o.color }} />
          {o.label} ±{o.window}h
          <Button variant="destructive" size="icon" className="h-4 w-4 text-[10px] leading-none" onClick={() => onRemove(i)}>
            ×
          </Button>
        </Badge>
      ))}
    </div>
  );
}
