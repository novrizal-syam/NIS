# Panduan Operasi dan Lapangan

## Lead Engineer (planner)
1. **Proyek** → buka proyek draf: susun WBS dan anggaran per elemen biaya (dari penawaran),
   kontingensi terkunci.
2. Ajukan anggaran; margin di bawah batas memerlukan persetujuan sesuai DOA. Setelah disetujui
   proyek **Terkunci** (baseline v0).
3. Perubahan anggaran hanya lewat **BCR** (Perubahan Anggaran); setiap BCR membuat versi baru.
4. Terima jasa vendor: **Penerimaan Barang** → GR jasa dari PO, unggah BAST, *Posting*.

## Engineer
- **Purchase Requisition** → *PR baru*: proyek, WBS, elemen biaya, tanggal butuh, item. Bila
  anggaran tidak cukup, PR **Terblokir**; ajukan BCR langsung dari layar PR.
- **Permintaan Material**: ambil stok dari gudang site lalu Base; kekurangan otomatis menjadi PR.

## Field Engineer (DOR harian)
1. **Daily Operation Report** → pilih proyek → *DOR baru*. Isi unit (jam operasi, standby,
   breakdown, rig-up), kru (jam, lembur), bahan kimia, data teknis dan HSE.
2. Tanpa sinyal: tetap isi dan *Simpan*; DOR terkirim otomatis saat online
   ("Belum tersinkron" → "Tersinkron").
3. *Ajukan* setelah tersinkron. Nilai DOR (tarif kontrak) tampil langsung.
4. Unit dengan sertifikat kedaluwarsa dan kru tanpa sertifikat wajib tidak bisa dipilih.

## OFS Superintendent
- Setujui DOR di Persetujuan Saya (cek jam, unit, bahan kimia). DOR yang disetujui menjadi
  dasar tiket layanan, biaya proyek dan hari kerja penggajian.

## Head of Operation
- Persetujuan PR sesuai batas, MR, dan pengajuan CAPEX; dasbor peran **Operation**
  (utilisasi aset, DOR menunggu, work order, insiden).
