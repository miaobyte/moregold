import { type ISeriesApi, type Time } from 'lightweight-charts';

export type Granularity = 1 | 5 | 15 | 30 | 60 | 240 | 720 | 1440 | 10080;
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
