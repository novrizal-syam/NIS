// id-ID formatting in Asia/Jakarta (CLAUDE.md rule 12). Money arrives from the API
// as integer rupiah (number or string); never do arithmetic on floats here.

export const TIMEZONE = 'Asia/Jakarta';

const idr = new Intl.NumberFormat('id-ID', {
  style: 'currency',
  currency: 'IDR',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const num = new Intl.NumberFormat('id-ID');

const shortDate = new Intl.DateTimeFormat('id-ID', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: TIMEZONE,
});

const dateTime = new Intl.DateTimeFormat('id-ID', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: TIMEZONE,
});

/** Replace the non-breaking spaces Intl emits so output is predictable. */
const NBSP = new RegExp('[\\u00a0\\u202f]', 'g');
const plain = (s: string) => s.replace(NBSP, ' ');

/** `1250000` -> `Rp 1.250.000` */
export function formatIDR(value: number | bigint | string): string {
  const v = typeof value === 'string' ? BigInt(value) : value;
  return plain(idr.format(v));
}

/** `1234567` -> `1.234.567` */
export function formatNumber(value: number | bigint): string {
  return num.format(value);
}

/** `2026-10-07` -> `7 Okt 2026` */
export function formatDate(value: Date | string): string {
  const d = typeof value === 'string' ? new Date(value) : value;
  // Intl id-ID writes "Agu" for August etc.; dots after short months are dropped.
  return plain(shortDate.format(d)).replace('.', '');
}

export function formatDateTime(value: Date | string): string {
  const d = typeof value === 'string' ? new Date(value) : value;
  return plain(dateTime.format(d));
}
