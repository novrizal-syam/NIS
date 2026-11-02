import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { formatDate, formatIDR } from '@/lib/format';

// Sample content for the component catalogue only (not business data).
const PILLS: { tone: StatusTone; label: string }[] = [
  { tone: 'neutral', label: 'Draft' },
  { tone: 'info', label: 'Diajukan' },
  { tone: 'warning', label: 'Menunggu persetujuan' },
  { tone: 'success', label: 'Disetujui' },
  { tone: 'danger', label: 'Diblokir anggaran' },
];

const ROWS: {
  no: string;
  project: string;
  date: string;
  amount: number;
  tone: StatusTone;
  status: string;
}[] = [
  {
    no: 'PR-26-031',
    project: 'PRJ-26-004 · Well testing Blok Rokan',
    date: '2026-10-07',
    amount: 125_000_000,
    tone: 'warning',
    status: 'Menunggu persetujuan',
  },
  {
    no: 'PR-26-030',
    project: 'PRJ-26-002 · EPF Jambi',
    date: '2026-10-05',
    amount: 48_750_000,
    tone: 'success',
    status: 'Disetujui',
  },
  {
    no: 'PR-26-029',
    project: 'PRJ-26-002 · EPF Jambi',
    date: '2026-10-02',
    amount: 312_400_000,
    tone: 'danger',
    status: 'Diblokir anggaran',
  },
  {
    no: 'PR-26-028',
    project: 'PRJ-26-001 · Nitrogen lifting',
    date: '2026-09-28',
    amount: 9_850_000,
    tone: 'neutral',
    status: 'Draft',
  },
];

const SWATCHES = [
  'brand-gold',
  'brand-ink',
  'brand-mist',
  'surface',
  'surface-muted',
  'surface-raised',
  'surface-inverse',
  'text',
  'text-body',
  'text-accent',
  'border',
  'success',
  'warning',
  'danger',
  'info',
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="font-heading text-section-title text-fg">{title}</h3>
      {children}
    </section>
  );
}

function Showcase({ theme }: { theme: 'light' | 'dark' }) {
  const [qty, setQty] = useState('');
  const qtyError =
    qty !== '' && !/^\d+$/.test(qty) ? 'Jumlah harus angka bulat, contoh: 12.' : undefined;
  const label = theme === 'light' ? 'Tema terang' : 'Tema gelap';

  return (
    <div
      data-theme={theme}
      data-testid={`showcase-${theme}`}
      className="flex min-w-0 flex-col gap-8 rounded-card bg-surface p-4 text-fg-body ring-1 ring-border md:p-6"
    >
      <div>
        <p className="eyebrow">Komponen · {label}</p>
        <h2 className="mt-1 text-page-title">Judul halaman</h2>
        <p className="mt-1 text-body text-fg-secondary">
          Deskripsi satu baris. Teks isi memakai Montserrat 14/22.
        </p>
        <p className="mt-2 text-caption text-fg-muted">
          Keterangan · diperbarui {formatDate('2026-10-07')}
        </p>
        <a
          href="#komponen"
          className="mt-2 inline-block text-small font-semibold text-fg-accent underline"
        >
          Tautan aksen
        </a>
      </div>

      <Section title="Tombol">
        <div className="flex flex-wrap gap-2">
          <Button variant="primary">
            <Icon name="send" /> Ajukan untuk persetujuan
          </Button>
          <Button variant="secondary">Simpan draft</Button>
          <Button variant="ghost">Batal</Button>
          <Button variant="destructive">
            <Icon name="block" /> Tolak
          </Button>
          <Button variant="secondary" disabled>
            Nonaktif
          </Button>
          <Button variant="secondary" size="icon" aria-label="Ekspor ke Excel">
            <Icon name="download" />
          </Button>
        </div>
      </Section>

      <Section title="Input">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Nama vendor" hint="Sesuai akta perusahaan." required>
            <Input placeholder="PT Contoh Abadi" />
          </Field>
          <Field label="Jumlah" error={qtyError}>
            <Input
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              placeholder="0"
            />
          </Field>
          <Field label="Elemen biaya">
            <Select defaultValue="">
              <option value="" disabled>
                Pilih elemen biaya
              </option>
              <option>5101 · Peralatan</option>
              <option>5102 · Personel</option>
              <option>5103 · Bahan habis pakai</option>
            </Select>
          </Field>
          <Field label="Contoh error">
            <Input defaultValue="abc" aria-invalid />
          </Field>
          <Field label="Catatan" className="sm:col-span-2">
            <Textarea placeholder="Alasan permintaan" />
          </Field>
        </div>
      </Section>

      <Section title="Status">
        <div className="flex flex-wrap gap-2">
          {PILLS.map((p) => (
            <StatusPill key={p.label} tone={p.tone}>
              {p.label}
            </StatusPill>
          ))}
        </div>
      </Section>

      <Section title="Kartu">
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <p className="eyebrow">Rencana · PRJ-26-004</p>
              <CardTitle>Anggaran tersedia</CardTitle>
              <CardDescription>Anggaran berjalan dikurangi komitmen dan realisasi.</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="font-heading text-page-title tabular-nums text-fg">
                {formatIDR(1_250_000_000)}
              </p>
              <div
                className="mt-3 h-2 rounded-pill bg-surface-muted"
                role="img"
                aria-label="Terpakai 62 persen"
              >
                <div className="h-2 w-[62%] rounded-pill bg-brand-gold" />
              </div>
              <p className="mt-1 text-small text-fg-secondary">Terpakai 62%</p>
            </CardContent>
          </Card>
          <Card className="bg-surface-inverse">
            <CardHeader>
              <CardTitle className="text-fg-on-inverse">Blok terbalik</CardTitle>
              <CardDescription className="text-fg-on-inverse">
                Teks di atas permukaan inverse.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <span className="inline-flex items-center rounded-pill bg-brand-gold px-2.5 py-0.5 text-small font-bold text-on-gold">
                3 menunggu
              </span>
            </CardContent>
          </Card>
        </div>
      </Section>

      <Section title="Tabel">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Cari" className="min-w-0 flex-1">
            <Input type="search" placeholder="Nomor atau proyek" />
          </Field>
          <Field label="Status" className="w-full sm:w-48">
            <Select defaultValue="all">
              <option value="all">Semua status</option>
              {PILLS.map((p) => (
                <option key={p.label}>{p.label}</option>
              ))}
            </Select>
          </Field>
          <Button variant="secondary">
            <Icon name="download" /> Ekspor Excel
          </Button>
        </div>
        <Card>
          <Table>
            <caption className="sr-only">Contoh daftar purchase requisition</caption>
            <THead>
              <TR>
                <TH>Nomor</TH>
                <TH>Proyek</TH>
                <TH>Tanggal</TH>
                <TH numeric>Nilai</TH>
                <TH>Status</TH>
              </TR>
            </THead>
            <TBody>
              {ROWS.map((r) => (
                <TR key={r.no}>
                  <TD className="font-semibold text-fg">{r.no}</TD>
                  <TD className="min-w-48">{r.project}</TD>
                  <TD className="whitespace-nowrap">{formatDate(r.date)}</TD>
                  <TD numeric className="whitespace-nowrap">
                    {formatIDR(r.amount)}
                  </TD>
                  <TD>
                    <StatusPill tone={r.tone}>{r.status}</StatusPill>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2 text-small text-fg-secondary">
            <span>Menampilkan 1–4 dari 31</span>
            <div className="flex gap-1">
              <Button variant="ghost" size="sm" aria-label="Halaman sebelumnya" disabled>
                <Icon name="chevron_left" />
              </Button>
              <Button variant="ghost" size="sm" aria-label="Halaman berikutnya">
                <Icon name="chevron_right" />
              </Button>
            </div>
          </div>
        </Card>
      </Section>

      <Section title="Warna">
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {SWATCHES.map((s) => (
            <li key={s} className="flex flex-col gap-1">
              <span
                className="h-10 rounded-control ring-1 ring-inset ring-border"
                style={{ background: `rgb(var(--${s}))` }}
              />
              <span className="truncate text-caption text-fg-muted">{s}</span>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

/** Development-only catalogue: every component rendered in both themes side by side. */
export function KomponenPage() {
  return (
    <div id="komponen" className="2xl:grid-cols-2 grid gap-6">
      <Showcase theme="light" />
      <Showcase theme="dark" />
    </div>
  );
}
