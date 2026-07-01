import type { Granularity } from '../types';

export const COLORS = ['#ff7043','#81c784','#ba68c8','#ffd54f','#4dd0e1','#f06292','#aed581','#ff8a65','#90a4ae','#64b5f6'];
export const MAIN_COLOR = '#ffffff';
export const GRAN_LABELS: Record<string, string> = { '1': '1分', '5': '5分', '60': '1时', '1440': '日' };
export const GRAN_OPTIONS: [string, string][] = [['auto','自动'],['1','1分'],['5','5分'],['60','1时'],['1440','日']];
export const RANGE_OPTIONS: [string, string][] = [['6','6h'],['12','12h'],['24','24h'],['48','2d'],['72','3d']];

export function getGranularity(visibleSec: number): Granularity {
  if (!visibleSec || visibleSec < 0) return 5;
  if (visibleSec < 12 * 3600) return 1;
  if (visibleSec < 3 * 86400) return 5;
  if (visibleSec < 14 * 86400) return 60;
  return 1440;
}
