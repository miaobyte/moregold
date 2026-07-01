import { useEffect, useRef } from 'react';
import { createSSE } from '../utils/api';
import type { ApiRow } from '../types';

export function useSSE(onPrice: (d: ApiRow) => void) {
  const esRef = useRef<EventSource | null>(null);

  const connect = () => {
    esRef.current?.close();
    let lastDt = '';
    esRef.current = createSSE(
      (d) => { if (d.dt !== lastDt) { lastDt = d.dt; onPrice(d); } },
      () => setTimeout(connect, 3000)
    );
  };

  useEffect(() => { connect(); return () => esRef.current?.close(); }, []);
}
