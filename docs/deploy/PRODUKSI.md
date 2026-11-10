# Panduan deployment produksi

Untuk tim IT GEK dan Nustrad. Target: satu VM di region Jakarta (atau VM + PostgreSQL
terkelola), HTTPS otomatis, backup harian teruji, dan pemantauan sederhana.

## 1. Kebutuhan

| Komponen | Minimum (20–40 pengguna) | Catatan |
| --- | --- | --- |
| VM | 4 vCPU, 8 GB RAM, 80 GB SSD | Ubuntu 24.04 LTS, region Jakarta (ap-southeast-3 atau setara) |
| Disk backup | 200 GB, disk terpisah | dipasang di `/srv/nustrad-backups` |
| PostgreSQL | 16 | di VM (`--profile local-db`) **atau** layanan terkelola region Jakarta |
| Object storage | S3-compatible, region Jakarta | bucket privat, versioning aktif |
| Domain | `erp.gek.co.id` (contoh) | record A ke IP publik VM |
| SMTP | akun relay perusahaan | untuk notifikasi, reset password, invoice |

Port terbuka: 80 dan 443 (publik), 22 hanya dari IP kantor/VPN. PostgreSQL tidak boleh
terbuka ke internet.

Data pribadi (UU 27/2022) dan dokumen keuangan disimpan di Indonesia: pilih region Jakarta
untuk VM, database, storage dan backup off-site.

## 2. Lingkungan terpisah

| | development | staging | production |
| --- | --- | --- | --- |
| Tempat | laptop (`docker compose up`) | VM kecil terpisah | VM produksi |
| Data | lokal/demo | salinan produksi hasil restore (latihan) | nyata |
| Kunci | contoh | milik sendiri | milik sendiri, salinan tersegel offline |

Rincian variabel: `deploy/env/README.md`. API menolak start di staging/produksi bila
`SECRET_KEY`, `DATA_ENCRYPTION_KEYS`, URL HTTPS atau secret storage tidak aman.

## 3. Instalasi pertama

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git mailutils
sudo mkdir -p /opt/nustrad /srv/nustrad-backups && cd /opt/nustrad
sudo git clone <url-repositori> . && sudo git checkout <tag-rilis>
```

1. Salin `deploy/env/production.env.example` ke `/opt/nustrad/.env`, isi semua nilai,
   `chmod 600 .env`. Tambahkan `ERP_DOMAIN`, `ACME_EMAIL` dan variabel `PG*`
   (`PGHOST`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`) untuk backup.
2. Buat kunci:
   `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` untuk `SECRET_KEY` dan
   `docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'"`
   untuk `DATA_ENCRYPTION_KEYS`. Simpan salinan tersegel kedua kunci di brankas Direksi:
   tanpa `DATA_ENCRYPTION_KEYS` NIK, NPWP pribadi dan rekening karyawan tidak bisa dibaca.
3. Jalankan:

```bash
docker compose -f deploy/prod/docker-compose.prod.yml --env-file .env up -d --build
```

   Dengan PostgreSQL di VM tambahkan `--profile local-db` (dan `PGHOST=db`).
   Layanan `migrate` menjalankan `alembic upgrade head` sebelum `api` dan `scheduler` start.
   Caddy (`web`) mengambil sertifikat Let's Encrypt sendiri dan memperbaruinya.
4. Buka `https://<ERP_DOMAIN>/setup`, masukkan `SETUP_TOKEN`, buat Super Admin pertama dan
   aktifkan 2FA. Hapus `SETUP_TOKEN` dari `.env` lalu
   `docker compose -f deploy/prod/docker-compose.prod.yml --env-file .env up -d`.
5. Ikuti `docs/admin/README.md` bagian Go-live.

Struktur layanan: `web` (Caddy: HTTPS, aplikasi web, proxy `/api`), `api` (2 worker),
`scheduler` (satu proses untuk job terjadwal: pengingat, notifikasi, WhatsApp, PDP),
`migrate` (sekali jalan), `backup` (cron harian 01:30 WIB), `db` (opsional).

## 4. Rilis baru

```bash
cd /opt/nustrad && git fetch --tags && git checkout <tag-baru>
bash deploy/backup/backup.sh            # backup tepat sebelum rilis (variabel PG* dari .env)
RELEASE=<tag-baru> docker compose -f deploy/prod/docker-compose.prod.yml --env-file .env up -d --build
curl -fsS https://<ERP_DOMAIN>/api/health
```

Rilis di luar jam kerja dan tidak di hari tutup buku. Migrasi hanya maju; bila rilis gagal,
kembali ke tag sebelumnya dan restore backup sebelum rilis (`deploy/backup/restore.sh`).

## 5. Backup dan restore

- Layanan `backup` menjalankan `deploy/backup/backup.sh` setiap hari 01:30 WIB: dump
  PostgreSQL (format custom, checksum SHA-256), 35 hari harian, bulanan disimpan 10 tahun
  (UU KUP pasal 28). `MC_SOURCE`/`MC_TARGET` mencerminkan object storage dan menyalin ke
  lokasi off-site (bucket lain di region Jakarta).
- Uji restore **setiap bulan** dan sebelum go-live:

```bash
bash deploy/backup/verify_restore.sh /srv/nustrad-backups/daily/<file>.dump
```

  Tanpa argumen skrip memakai dump terbaru. Skrip memulihkan ke database sementara lalu
  membandingkan versi migrasi, jumlah baris tabel kunci, neraca saldo nol dan data pribadi
  yang tetap terenkripsi; kode keluar ≠ 0 bila ada beda. Catat hasilnya di checklist go-live.
- Restore produksi (bencana): hentikan `api` dan `scheduler`, jalankan
  `deploy/backup/restore.sh <file>.dump nustrad --yes`, lalu start lagi. RPO 24 jam, RTO < 4 jam.

## 6. Pemantauan

- `deploy/monitoring/check.sh` lewat cron setiap 5 menit: API dan database sehat, sertifikat
  TLS > 14 hari, backup terakhir < 26 jam, disk < 85 %. Masalah dikirim ke `ALERT_EMAIL`;
  `HEARTBEAT_URL` (mis. healthchecks.io) dipanggil saat semua sehat, sehingga VM yang mati
  pun ketahuan.

```bash
echo '*/5 * * * * root ERP_URL=https://erp.gek.co.id ALERT_EMAIL=it@gek.co.id BACKUP_DIR=/srv/nustrad-backups /opt/nustrad/deploy/monitoring/check.sh' | sudo tee /etc/cron.d/nustrad-check
```

- Tambahkan pemantau uptime eksternal ke `https://<ERP_DOMAIN>/api/health`.
- Log: `docker compose ... logs -f api` (JSON, satu baris per request dengan `request_id`);
  rotasi 10 × 20 MB per layanan. Log akses Caddy di volume `caddy-data`.
- Di aplikasi: Pengaturan → Integrasi (status kanal), Audit, dan Peta proses di Dasbor.

## 7. Keamanan operasional

- Pembaruan OS otomatis (`unattended-upgrades`), SSH hanya kunci, tanpa login root.
- Rotasi kunci enkripsi: tambahkan kunci baru di depan `DATA_ENCRYPTION_KEYS`
  (`baru,lama`), restart, lalu kunci lama boleh dicabut setelah data dienkripsi ulang.
- Tinjauan akses per kuartal (Pengaturan → Tinjauan akses), log kebocoran data di
  Pengaturan → Data pribadi (PDP); pemberitahuan ke subjek dan otoritas paling lambat 3×24 jam.
- Mode `production` mematikan `/api/docs`; dokumentasi API ada di `docs/api/`.
