# Dashboard Monitoring

A Streamlit app for monitoring teknisi and konsumen projects.

## Deploy to Streamlit Community Cloud

1. Buat repository GitHub dari folder ini.
2. Pastikan file berikut ada:
   - `rev.py`
   - `requirements.txt`
   - `.streamlit/config.toml`
3. Push ke GitHub:

```bash
git init
git add .
git commit -m "Initial deploy"
git branch -M main
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

4. Buka https://share.streamlit.io dan klik **New app**.
5. Pilih repo, branch `main`, dan file `rev.py`.
6. Deploy.

## Catatan penting

- `monitoring.db` adalah database SQLite lokal, tidak cocok untuk penyimpanan jangka panjang di Streamlit Cloud.
- Jika butuh data persisten, gunakan database eksternal seperti PostgreSQL, MySQL, atau layanan lain.
