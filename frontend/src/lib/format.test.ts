import { formatDate, formatDateTime, formatIDR, formatNumber } from './format';

describe('id-ID formatting', () => {
  it('formats rupiah', () => {
    expect(formatIDR(1_250_000)).toBe('Rp 1.250.000');
    expect(formatIDR('25000000000')).toBe('Rp 25.000.000.000');
    expect(formatIDR(0)).toBe('Rp 0');
    expect(formatIDR('1.250E+7')).toBe('Rp 12.500.000');
    expect(formatIDR('-750000')).toBe('-Rp 750.000');
    expect(() => formatIDR('abc')).toThrow();
  });

  it('formats plain numbers', () => {
    expect(formatNumber(1_234_567)).toBe('1.234.567');
  });

  it('formats dates as "7 Okt 2026" in Jakarta time', () => {
    expect(formatDate('2026-10-07T03:00:00+07:00')).toBe('7 Okt 2026');
    // 23:30 UTC on 6 Oct is already 7 Oct in Jakarta.
    expect(formatDate('2026-10-06T23:30:00Z')).toBe('7 Okt 2026');
    expect(formatDateTime('2026-10-06T23:30:00Z')).toContain('06.30');
  });
});
