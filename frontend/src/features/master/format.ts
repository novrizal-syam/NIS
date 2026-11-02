import type { TFunction } from 'i18next';
import { formatDate, formatIDR } from '@/lib/format';
import type { FieldMeta } from './api';

/** Display value of one field in tables (id-ID formats, choice labels). */
export function display(f: FieldMeta, value: unknown, t: TFunction): string {
  if (value === null || value === undefined || value === '') return '–';
  switch (f.kind) {
    case 'idr':
      return formatIDR(String(value));
    case 'decimal':
    case 'int':
      return Number(value).toLocaleString('id-ID');
    case 'bool':
      return value ? t('master.yes') : t('master.no');
    case 'date':
      return formatDate(String(value));
    case 'choice':
      return f.choices.find((c) => c.value === value)?.label ?? String(value);
    case 'docs':
      return String((value as unknown[]).length);
    default:
      return String(value);
  }
}

export const isNumeric = (f: FieldMeta) =>
  f.kind === 'idr' || f.kind === 'decimal' || f.kind === 'int';
