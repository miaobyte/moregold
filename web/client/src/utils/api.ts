import type { ApiRow } from '../types';

const BASE = '/api';

export async function fetchRecent(hours: number, granularity: number): Promise<ApiRow[]> {
  const r = await fetch(`${BASE}/recent?hours=${hours}&granularity=${granularity}`);
  return r.json();
}

export async function fetchAround(dt: string, hours: number, granularity: number): Promise<ApiRow[]> {
  const r = await fetch(`${BASE}/around?dt=${encodeURIComponent(dt)}&hours=${hours}&granularity=${granularity}`);
  return r.json();
}

export function createSSE(onMessage: (data: ApiRow) => void, onError: () => void): EventSource {
  const es = new EventSource(`${BASE}/stream`);
  es.onmessage = (e) => onMessage(JSON.parse(e.data));
  es.onerror = () => { es.close(); onError(); };
  return es;
}
