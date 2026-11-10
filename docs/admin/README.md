# Panduan Admin Nustrad ERP

Untuk Super Admin dan Admin IT PT Global Energi KITA. Instalasi server ada di
`docs/deploy/PRODUKSI.md`; panduan per peran untuk pengguna ada di `docs/panduan/`.

## 1. Peran admin

| Peran | Boleh | Tidak boleh |
| --- | --- | --- |
| Super Admin | semua pengaturan, hapus data demo, membuka akses darurat | menyetujui dokumen bisnis atas nama orang lain |
| Admin | pengguna, peran, data master, integrasi | hapus data demo, mengubah Super Admin terakhir |

Selalu ada minimal satu Super Admin aktif; sistem menolak menonaktifkan yang terakhir.
Simpan kode pemulihan 2FA Super Admin di brankas.

## 2. Go-live langkah demi langkah

Buka **Pengaturan → Go-live**. Daftar periksa menunjukkan butir yang masih kurang, masing-masing
dengan tautan ke layar perbaikannya.

1. **Hapus data demo** — Pengaturan → Data demo → *Hapus semua data demo* (Super Admin).
   Hanya baris `is_demo` yang dihapus; konfigurasi (bagan akun, elemen biaya, aturan DOA)
   tetap.
2. **Profil perusahaan** — nama resmi, NPWP, alamat, logo (dipakai di kop surat, invoice,
   faktur dan e-Faktur XML).
3. **Data master** — klien, vendor (status CSMS, NPWP, rekening), karyawan (gaji, PTKP, NIK,
   rekening — terenkripsi), item, gudang, aset dan sertifikatnya, daftar harga.
   Gunakan impor Excel di tiap daftar Data Master.
4. **Rekening bank** — Treasury → Rekening & rekonsiliasi; cocokkan nomor rekening dengan buku bank.
5. **Pengguna dan peran** — undang setiap pengguna (e-mail undangan), beri satu atau lebih
   peran. Peran kunci yang wajib terisi: Direktur, Head of Finance, Lead Controller,
   AP Accountant, Kasir. Periksa Pemisahan Tugas (Pengaturan → Pemisahan Tugas).
6. **Aturan DOA** — Pengaturan → Aturan DOA: batas nilai dan penyetuju per jenis dokumen.
   Perubahan aturan tercatat dan berlaku untuk pengajuan baru.
7. **Periode akuntansi** — Data Master → Periode: 12 periode tahun berjalan terbuka.
8. **Saldo awal** — diposting oleh Lead Controller atau Head of Finance (izin menyetujui
   Keuangan) di Go-live atau Buku Besar & Laporan → Saldo awal:
   1. isi tanggal go-live (tanggal tutup sistem lama) dan unduh templat Excel;
   2. isi sheet GL, AR, AP, Stock, Assets (kode diambil dari sheet *Referensi*);
   3. unggah dan klik **Periksa** — tidak ada yang disimpan; perbaiki baris yang ditolak;
   4. bila ringkasan seimbang, klik **Posting saldo awal**. Ini hanya bisa sekali;
      koreksi berikutnya lewat jurnal manual (DOA Lead Controller).
9. **E-mail dan integrasi** — SMTP di `.env`; Pengaturan → Integrasi untuk WhatsApp,
   PJAP (e-Faktur), PSrE, e-Meterai dan host-to-host bank. Tanpa kredensial, kanal berjalan
   dalam mode manual/berkas.
10. **Backup** — pastikan backup harian berjalan dan uji restore berhasil
    (`deploy/backup/verify_restore.sh`), lalu centang butir manual.
11. **Pelatihan pengguna** — bagikan panduan peran (`docs/panduan/`), latihan di staging.

Setelah semua hijau, umumkan tanggal mulai dan matikan input di sistem lama.

## 3. Pekerjaan rutin

| Kapan | Apa | Di mana |
| --- | --- | --- |
| Harian | periksa notifikasi gagal kirim, outbox WhatsApp | Pengaturan → Integrasi |
| Mingguan | pengguna baru/keluar, delegasi yang habis | Pengguna & Peran |
| Bulanan | uji restore backup, laporan audit | server; Jejak Audit |
| Kuartalan | tinjauan akses oleh atasan | Pengaturan → Tinjauan Akses |
| Saat ada insiden data pribadi | catat dalam 24 jam, beri tahu dalam 3×24 jam | Pengaturan → Data pribadi (PDP) |

## 4. Pengguna

- **Undang**: Pengguna & Peran → *Undang*. Pengguna membuat kata sandi, wajib 2FA bila
  perannya mensyaratkan, dan menyetujui pemberitahuan privasi.
- **Keluar/mutasi**: nonaktifkan (jangan hapus); dokumen dan jejak audit tetap atas namanya.
  Pindahkan persetujuan yang tertunda dengan delegasi.
- **Portal klien/vendor**: beri peran *Client Representative* atau *Vendor*, lalu hubungkan
  ke kode klien/vendor (Portal klien & vendor → *Hubungkan akun portal*). Tanpa tautan, akun
  portal tidak melihat apa pun.
- **Data sensitif** (gaji, NIK, rekening, NPWP pribadi) hanya tampil untuk izin khusus;
  tanpa izin, field dihapus dari API dan ekspor.

## 5. Masalah umum

| Gejala | Penyebab biasa | Tindakan |
| --- | --- | --- |
| "Periode ditutup" saat posting | periode sudah ditutup Lead Controller | minta HoF membuka kembali dengan alasan |
| PR "Terblokir" | anggaran tidak cukup | ajukan BCR dari layar PR |
| Persetujuan tidak muncul | tidak ada pemegang peran / delegasi habis | periksa Pengguna & Aturan DOA |
| Notifikasi tidak terkirim | SMTP salah | cek Pengaturan → Integrasi dan log `api` |
| Pengguna terkunci | salah sandi berulang | Pengguna & Peran → pengguna → buka kunci |

Setiap respons galat API memuat `code` dan pesan; log server memuat `request_id` yang sama
untuk penelusuran.
