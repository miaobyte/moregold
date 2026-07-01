import { type ISeriesApi, type Time, type SeriesDataItemTypeMap } from 'lightweight-charts';

export type Granularity = 1 | 5 | 60 | 1440;
export type PriceMode = 'usd' | 'cny';

export interface PricePoint {
  time: Time;
  value: number;
  usd: number;
  cny: number;
  origTime?: number;
}

export interface Overlay {
  dt: string;
  window: number;
  color: string;
  label: string;
  series: ISeriesApi<'Line'> | null;
  offset: number;
  timeShift: number;
  data: PricePoint[] | null;
}

export interface ApiRow {
  dt: string;
  usd: number;
  cny: number;
}

export interface DragState {
  ov: Overlay;
  startX: number;
  startY: number;
  startPrice: number;
  startTime: number;
  initOffset: number;
  initTimeShift: number;
  initDt: string;
  lastFetch: number;
}
