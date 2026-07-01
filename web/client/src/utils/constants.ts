import type { Granularity } from '../types';

export const COLORS = ['#ff7043','#81c784','#ba68c8','#ffd54f','#4dd0e1','#f06292','#aed581','#ff8a65','#90a4ae','#64b5f6'];
export const MAIN_COLOR = '#ffffff';
export const GRAN_OPTIONS: [string, string][] = [
  ['auto','自动'],['1','1分'],['5','5分'],['15','15分'],['30','30分'],
  ['60','1时'],['240','4时'],['720','12时'],['1440','日'],['10080','周'],
];
export const RANGE_OPTIONS: [string, string][] = [['6','6h'],['12','12h'],['24','24h'],['48','2d'],['72','3d']];

export function getGranularity(visibleSec: number): Granularity {
  if (!visibleSec || visibleSec < 0) return 5;
  if (visibleSec < 2 * 3600) return 1;
  if (visibleSec < 6 * 3600) return 5;
  if (visibleSec < 12 * 3600) return 15;
  if (visibleSec < 1.5 * 86400) return 30;
  if (visibleSec < 4 * 86400) return 60;
  if (visibleSec < 10 * 86400) return 240;
  if (visibleSec < 30 * 86400) return 720;
  if (visibleSec < 90 * 86400) return 1440;
  return 10080;
}
