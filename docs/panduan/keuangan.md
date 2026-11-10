# Panduan Keuangan

Setiap transaksi keuangan memposting jurnal seimbang otomatis. Dokumen yang sudah diposting
hanya bisa dibalik, bukan diedit.

## Billing Admin (order to cash)
1. **Service Ticket**: buat tiket dari DOR yang disetujui untuk rentang tanggal.
2. Klien menandatangani di tablet atau lewat tautan; baris yang disengketakan dipisahkan
   (register sengketa) dan tidak ditagih.
3. **Invoice** dari tiket yang sudah ditandatangani: DPP nilai lain 11/12, PPN 12 %, perkiraan
   PPh 23, bea meterai. Isi nomor faktur pajak; ekspor XML Coretax atau kirim lewat PJAP.
4. *Kirim*: paket invoice PDF (invoice, tiket, faktur) ke e-mail klien.
5. **Penerimaan Kas**: impor mutasi bank (CSV/MT940); sistem mencocokkan nomor invoice.
   Konfirmasi; selisih = PPh 23 dipotong klien (bukti potong menyusul).

## AP Accountant
1. **Tagihan Vendor**: pilih PO, isi nomor invoice dan faktur, unggah dokumen, *Cocokkan 3 arah*
   (PO–GR–invoice). Sesuai → disetujui dan siap bayar; selisih → exception.
2. **Treasury → Payment run**: pilih tagihan jatuh tempo dan gaji, *Ajukan*. Anda tidak bisa
   menyetujui atau merilis run yang Anda siapkan.

## Kasir
- Rilis payment run yang sudah disetujui, unduh berkas bank (atau kirim host-to-host),
  rekonsiliasi rekening.

## Tax Specialist
- **Pajak**: lembar kerja per masa (PPN, PPh 21, PPh 23, PPh 4(2)). Isi kode billing,
  bayar (NTPN), lapor (BPE). PPN lebih bayar dikompensasikan otomatis ke masa berikutnya.

## Lead Controller
- **Buku Besar & Laporan**: neraca saldo, buku besar, laba rugi, neraca, arus kas (Excel/PDF).
- Jurnal manual (disetujui sesuai DOA), aturan posting.
- **Tutup buku** bulanan: semua pemeriksaan pemblokir hijau (DOR, neraca saldo), penyusutan
  dijalankan, catatan wajib bila ada peringatan. Setelah ditutup, posting ke periode itu
  ditolak.

## Head of Finance
- Persetujuan PR/PO/BCR sesuai batas, penggajian, payment run.
- Membuka kembali periode yang ditutup (alasan wajib, tercatat di riwayat).
