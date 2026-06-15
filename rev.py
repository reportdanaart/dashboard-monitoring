import streamlit as st
import pandas as pd
import sqlite3
import random
import requests
from datetime import datetime
import pydeck as pdk
import plotly.graph_objects as go
import plotly.express as px
from io import BytesIO

# =========================
# KONFIGURASI
# =========================
st.set_page_config(layout="wide", page_title="Dashboard Teknisi")

# =========================
# DATABASE
# =========================
conn = sqlite3.connect("monitoring.db", check_same_thread=False)
c = conn.cursor()

def gen_id(prefix):
    """Generate a unique ID with the given prefix."""
    for _ in range(10):
        new_id = f"{prefix}{random.randint(100000, 999999)}"
        exists = c.execute(
            """
            SELECT 1 FROM teknisi WHERE id=?
            UNION SELECT 1 FROM konsumen WHERE id=?
            UNION SELECT 1 FROM assign WHERE id=?
            UNION SELECT 1 FROM assign_archive WHERE id=?
            """,
            (new_id, new_id, new_id, new_id)
        ).fetchone()
        if not exists:
            return new_id
    return f"{prefix}{int(datetime.now().timestamp() * 1000)}"

def safe_add_column(table_name, column_def):
    """Add column if not exists."""
    col_name = column_def.split()[0]
    try:
        c.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")
        conn.commit()
    except sqlite3.OperationalError:
        pass

# =========================
# TABEL
# =========================
c.execute("""
CREATE TABLE IF NOT EXISTS teknisi (
    id TEXT PRIMARY KEY,
    nama TEXT,
    alamat TEXT,
    telp TEXT,
    area TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS konsumen (
    id TEXT PRIMARY KEY,
    nama TEXT,
    alamat TEXT,
    telp TEXT,
    pj TEXT,
    jenis_project TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS assign (
    id TEXT PRIMARY KEY,
    nama_teknisi TEXT,
    tgl TEXT,
    alamat TEXT,
    status TEXT,
    lat REAL,
    long REAL,
    jenis_project TEXT,
    konsumen_nama TEXT
)
""")

c.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_assign_unique
ON assign (nama_teknisi, alamat, tgl, jenis_project)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS assign_archive (
    id TEXT PRIMARY KEY,
    nama_teknisi TEXT,
    tgl TEXT,
    alamat TEXT,
    status TEXT,
    lat REAL,
    long REAL,
    jenis_project TEXT,
    deleted_at TEXT,
    konsumen_nama TEXT
)
""")

conn.commit()

# =========================
# MIGRASI KOLOM
# =========================
try:
    c.execute("ALTER TABLE assign ADD COLUMN konsumen_nama TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass

try:
    c.execute("ALTER TABLE assign_archive ADD COLUMN konsumen_nama TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass

# =========================
# STATUS UPDATE FLOW
# =========================
PROGRESS_FLOW = ["mulai", "proses", "done", "perbaikan", "done final"]
STATUS_EMOJI = {
    "mulai": "🟢",
    "proses": "🟡",
    "done": "🔵",
    "perbaikan": "🟠",
    "done final": "✅",
}
STATUS_COLOR = {
    "mulai": "#28a745",
    "proses": "#ffc107",
    "done": "#17a2b8",
    "perbaikan": "#fd7e14",
    "done final": "#6f42c1",
}
STATUS_ALIAS = {
    "baru dimulai": "mulai",
    "selesai": "done",
    "finish": "done final",
    "done final": "done final",
}

def normalize_status(s):
    s = str(s or "mulai").strip().lower()
    return STATUS_ALIAS.get(s, s if s in PROGRESS_FLOW else "mulai")

def next_status(current):
    current = normalize_status(current)
    idx = PROGRESS_FLOW.index(current)
    return PROGRESS_FLOW[min(idx + 1, len(PROGRESS_FLOW) - 1)]

def prev_status(current):
    current = normalize_status(current)
    idx = PROGRESS_FLOW.index(current)
    return PROGRESS_FLOW[max(idx - 1, 0)]

def render_progress_bar(current):
    current = normalize_status(current)
    idx = PROGRESS_FLOW.index(current)
    total = len(PROGRESS_FLOW)

    items = []
    for i, step in enumerate(PROGRESS_FLOW):
        if i < idx:
            dot_style = f"background:{STATUS_COLOR[step]};color:white;border:2px solid {STATUS_COLOR[step]};"
            label_style = f"color:{STATUS_COLOR[step]};font-weight:600;"
            dot_text = "✓"
        elif i == idx:
            dot_style = f"background:{STATUS_COLOR[step]};color:white;border:3px solid white;box-shadow:0 0 0 2px {STATUS_COLOR[step]};"
            label_style = f"color:{STATUS_COLOR[step]};font-weight:800;"
            dot_text = STATUS_EMOJI.get(step, "●")
        else:
            dot_style = "background:#444;color:#888;border:2px solid #555;"
            label_style = "color:#666;"
            dot_text = str(i + 1)

        step_html = f"""
        <div style="display:flex;flex-direction:column;align-items:center;flex:1;">
            <div style="width:28px;height:28px;border-radius:50%;{dot_style}display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:bold;">
                {dot_text}
            </div>
            <div style="font-size:10px;margin-top:4px;text-align:center;{label_style}">{step.upper()}</div>
        </div>
        """

        items.append(step_html)

        if i < total - 1:
            line_color = STATUS_COLOR[step] if i < idx else "#444"
            items.append(
                f'<div style="flex:0.5;height:3px;background:{line_color};margin-top:13px;"></div>'
            )

    return f"""
    <div style="background:#1a1a2e;border-radius:10px;padding:10px 16px 6px;margin-bottom:6px;">
        <div style="display:flex;align-items:flex-start;width:100%;">{''.join(items)}</div>
    </div>
    """

# =========================
# NAVIGASI
# =========================
st.sidebar.title("🚀 Navigasi")
menu = st.sidebar.radio(
    "Menu Utama",
    ["Monitoring Project", "Analytics Dashboard", "Master Teknisi", "Master Konsumen", "Assign Project", "Update Status"]
)

# =========================
# MENU 1: MONITORING PROJECT
# =========================
if menu == "Monitoring Project":
    st.title("📈 Analisis Monitoring")

    query = """
        SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama
        FROM assign
        ORDER BY tgl DESC
    """
    df = pd.read_sql(query, conn)

    if df.empty:
        st.info("Belum ada data pengerjaan.")
    else:
        df["nama_konsumen"] = df["konsumen_nama"]

        st.sidebar.subheader("Filter Monitoring")
        tek = st.sidebar.selectbox("Filter Teknisi", ["Semua"] + df["nama_teknisi"].dropna().unique().tolist())
        ks = st.sidebar.selectbox("Filter Konsumen", ["Semua"] + df["nama_konsumen"].fillna("N/A").unique().tolist())
        jp = st.sidebar.selectbox("Filter Jenis Project", ["Semua"] + df["jenis_project"].dropna().unique().tolist())

        df["tgl_dt"] = pd.to_datetime(df["tgl"], errors="coerce")
        min_date = df["tgl_dt"].min().date() if df["tgl_dt"].notna().any() else datetime.today().date()
        start_date = st.sidebar.date_input("Dari Tanggal", value=min_date)

        filtered = df.copy()
        if tek != "Semua":
            filtered = filtered[filtered["nama_teknisi"] == tek]
        if ks != "Semua":
            filtered = filtered[filtered["nama_konsumen"] == ks]
        if jp != "Semua":
            filtered = filtered[filtered["jenis_project"] == jp]

        filtered = filtered[filtered["tgl_dt"] >= pd.to_datetime(start_date)]

        st.metric("Total Tugas", len(filtered))

        col1, col2 = st.columns([0.8, 0.2])
        with col1:
            st.dataframe(filtered, use_container_width=True)
        with col2:
            if not filtered.empty:
                buffer = BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    filtered.to_excel(writer, index=False, sheet_name="Monitoring")
                buffer.seek(0)
                st.download_button(
                    label="📥 Download",
                    data=buffer.getvalue(),
                    file_name="Monitoring_Project.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        if not filtered.empty:
            st.subheader("Peta Lokasi Proyek")
            df_map = filtered.dropna(subset=["lat", "long"]).copy()
            df_map["lat"] = pd.to_numeric(df_map["lat"], errors="coerce")
            df_map["long"] = pd.to_numeric(df_map["long"], errors="coerce")
            df_map = df_map.dropna(subset=["lat", "long"])

            if not df_map.empty:
                tek_uniques = df_map["nama_teknisi"].fillna("Unknown").unique().tolist()
                bright_colors = [
                    (255, 0, 0), (0, 0, 255), (0, 200, 0), (255, 165, 0),
                    (255, 0, 255), (0, 255, 255), (255, 255, 0), (128, 0, 128),
                    (255, 128, 0), (0, 128, 255),
                ]
                color_map = {name: bright_colors[i % len(bright_colors)] for i, name in enumerate(tek_uniques)}

                df_map["r"] = df_map["nama_teknisi"].fillna("Unknown").map(lambda x: color_map.get(x, (255, 0, 0))[0])
                df_map["g"] = df_map["nama_teknisi"].fillna("Unknown").map(lambda x: color_map.get(x, (255, 0, 0))[1])
                df_map["b"] = df_map["nama_teknisi"].fillna("Unknown").map(lambda x: color_map.get(x, (255, 0, 0))[2])

                proj_uniques = df_map["jenis_project"].fillna("Unknown").unique().tolist()
                radius_map = {name: 100 + idx * 100 for idx, name in enumerate(proj_uniques)}
                df_map["radius"] = df_map["jenis_project"].fillna("Unknown").map(lambda x: radius_map.get(x, 100))

                df_map["konsumen_letter"] = df_map["nama_konsumen"].fillna("?").apply(lambda x: str(x)[0].upper() if str(x) else "?")
                df_map["project_text"] = df_map["jenis_project"].fillna("?").apply(lambda x: str(x)[:20])

                legend_df = pd.DataFrame([(k, f"rgb{color_map[k]}") for k in color_map], columns=["Teknisi", "Color"])
                proj_legend_df = pd.DataFrame([(k, f"{radius_map.get(k, 100)} px") for k in proj_uniques], columns=["Jenis Project", "Radius"])

                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("🎨 Legend: Teknisi (Warna)")
                    st.dataframe(legend_df, use_container_width=True)
                with col2:
                    st.subheader("⭕ Legend: Jenis Project (Ukuran)")
                    st.dataframe(proj_legend_df, use_container_width=True)

                layer_circles = pdk.Layer(
                    "ScatterplotLayer",
                    df_map,
                    get_position='[long, lat]',
                    get_radius='radius',
                    get_fill_color='[r, g, b, 200]',
                    pickable=True
                )

                layer_text_konsumen = pdk.Layer(
                    "TextLayer",
                    df_map,
                    get_position='[long, lat]',
                    get_text='konsumen_letter',
                    get_size=24,
                    get_color=[255, 255, 255],
                    get_text_anchor='"middle"',
                    get_alignment_baseline='"center"'
                )

                layer_text_project = pdk.Layer(
                    "TextLayer",
                    df_map,
                    get_position='[long, lat]',
                    get_text='project_text',
                    get_size=12,
                    get_color=[255, 255, 255],
                    get_text_anchor='"middle"',
                    get_alignment_baseline='"top"'
                )

                view = pdk.ViewState(
                    latitude=df_map["lat"].mean(),
                    longitude=df_map["long"].mean(),
                    zoom=12
                )

                st.pydeck_chart(
                    pdk.Deck(
                        layers=[layer_circles, layer_text_konsumen, layer_text_project],
                        initial_view_state=view,
                        tooltip={"text": "{nama_teknisi}\n{jenis_project}\n{nama_konsumen}"}
                    )
                )

# =========================
# MENU 2: ANALYTICS DASHBOARD
# =========================
elif menu == "Analytics Dashboard":
    st.title("📊 Analytics Dashboard Profesional")

    df_all = pd.read_sql("""
        SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama
        FROM assign
        ORDER BY tgl DESC
    """, conn)

    if df_all.empty:
        st.info("Belum ada data penugasan untuk dianalisis.")
    else:
        df_all["tgl_dt"] = pd.to_datetime(df_all["tgl"], errors="coerce")

        st.subheader("📈 Key Performance Indicators")
        col1, col2, col3, col4, col5 = st.columns(5)

        total_projects = len(df_all)
        total_done = len(df_all[df_all["status"].apply(normalize_status) == "done"])
        total_in_progress = len(df_all[df_all["status"].apply(normalize_status).isin(["mulai", "proses", "perbaikan"])])
        completion_rate = (total_done / total_projects * 100) if total_projects else 0
        unique_teknisi = df_all["nama_teknisi"].nunique()

        col1.metric("Total Proyek", total_projects)
        col2.metric("✅ Selesai (Done)", total_done)
        col3.metric("⏳ Dalam Proses", total_in_progress)
        col4.metric("📊 Completion Rate", f"{completion_rate:.1f}%")
        col5.metric("👥 Total Teknisi Aktif", unique_teknisi)

        st.divider()

        st.subheader("📊 Distribusi Status Pengerjaan")
        df_all["status_norm"] = df_all["status"].apply(normalize_status)
        status_counts = df_all["status_norm"].value_counts()

        col1, col2 = st.columns(2)
        with col1:
            fig_pie = px.pie(values=status_counts.values, names=status_counts.index, title="Status Penugasan", color_discrete_sequence=px.colors.qualitative.Set2)
            st.plotly_chart(fig_pie, use_container_width=True)
        with col2:
            status_df = pd.DataFrame({"Status": status_counts.index, "Jumlah": status_counts.values})
            fig_bar = px.bar(status_df, x="Status", y="Jumlah", title="Jumlah Proyek per Status", text_auto=True, color="Status")
            st.plotly_chart(fig_bar, use_container_width=True)

        st.divider()

        st.subheader("👨‍🔧 Performa Teknisi")
        teknisi_stats = df_all.groupby("nama_teknisi").agg(
            **{
                "Total Proyek": ("id", "count"),
                "Selesai": ("status_norm", lambda x: (x == "done").sum())
            }
        )
        teknisi_stats["% Completion"] = (teknisi_stats["Selesai"] / teknisi_stats["Total Proyek"] * 100).round(2)
        teknisi_stats = teknisi_stats.sort_values("Total Proyek", ascending=False)

        col1, col2 = st.columns(2)
        with col1:
            tek_df = teknisi_stats.reset_index()
            fig_tek = px.bar(tek_df, x="nama_teknisi", y="Total Proyek", title="Jumlah Proyek per Teknisi", text_auto=True)
            st.plotly_chart(fig_tek, use_container_width=True)
        with col2:
            tek_rate_df = teknisi_stats.reset_index()
            fig_tek_rate = px.bar(tek_rate_df, x="nama_teknisi", y="% Completion", title="Completion Rate per Teknisi", text_auto=True)
            st.plotly_chart(fig_tek_rate, use_container_width=True)

        st.dataframe(teknisi_stats.reset_index(), use_container_width=True)

# =========================
# MENU 3: MASTER TEKNISI
# =========================
elif menu == "Master Teknisi":
    st.title("👨‍🔧 Master Teknisi")

    st.subheader("📥 Import dari Excel")
    uploaded_file = st.file_uploader("Upload file Excel (Columns: nama, alamat, telp, area)", type="xlsx")
    if uploaded_file:
        try:
            df_import = pd.read_excel(uploaded_file)
            st.dataframe(df_import, use_container_width=True)

            if st.button("Import Data Teknisi"):
                imported, failed = 0, 0
                for _, row in df_import.iterrows():
                    try:
                        n, a, t, ar = row.get("nama"), row.get("alamat"), row.get("telp"), row.get("area")
                        cek_nama = c.execute("SELECT id FROM teknisi WHERE nama=?", (n,)).fetchone()
                        cek_telp = c.execute("SELECT id FROM teknisi WHERE telp=?", (t,)).fetchone()
                        if not cek_nama and not cek_telp:
                            c.execute("INSERT INTO teknisi VALUES (?,?,?,?,?)", (gen_id("TK"), n, a, t, ar))
                            imported += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                conn.commit()
                st.success(f"✅ {imported} teknisi berhasil diimport, {failed} baris gagal/duplikat")
                st.rerun()
        except Exception as e:
            st.error(f"Error membaca file: {e}")

    st.divider()
    st.subheader("➕ Tambah Teknisi Manual")
    with st.form("add_tk", clear_on_submit=True):
        n = st.text_input("Nama")
        a = st.text_input("Alamat")
        t = st.text_input("No Telp")
        ar = st.text_input("Area")
        if st.form_submit_button("Simpan"):
            cek_nama = c.execute("SELECT id FROM teknisi WHERE nama=?", (n,)).fetchone()
            cek_telp = c.execute("SELECT id FROM teknisi WHERE telp=?", (t,)).fetchone()

            if cek_nama:
                st.error(f"Nama '{n}' sudah terdaftar.")
            elif cek_telp:
                st.error(f"No Telp '{t}' sudah digunakan.")
            else:
                try:
                    c.execute("INSERT INTO teknisi VALUES (?,?,?,?,?)", (gen_id("TK"), n, a, t, ar))
                    conn.commit()
                    st.success("Teknisi berhasil ditambahkan!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Terjadi kesalahan: {e}")

    st.divider()
    df = pd.read_sql("SELECT * FROM teknisi", conn)
    edited = st.data_editor(df, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Simpan Perubahan", key="btn_save_teknisi"):
            for _, r in edited.iterrows():
                c.execute(
                    "UPDATE teknisi SET nama=?, alamat=?, telp=?, area=? WHERE id=?",
                    (r["nama"], r["alamat"], r["telp"], r["area"], r["id"])
                )
            conn.commit()
            st.rerun()

    with col2:
        if not df.empty:
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Teknisi")
            buffer.seek(0)
            st.download_button(
                label="📥 Download Excel",
                data=buffer.getvalue(),
                file_name="Master_Teknisi.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# =========================
# MENU 4: MASTER KONSUMEN
# =========================
elif menu == "Master Konsumen":
    st.title("🏢 Master Konsumen")

    st.subheader("📥 Import dari Excel")
    uploaded_file = st.file_uploader("Upload file Excel (Columns: nama, alamat, telp, pj, jenis_project)", type="xlsx")
    if uploaded_file:
        try:
            df_import = pd.read_excel(uploaded_file)
            st.dataframe(df_import, use_container_width=True)

            if st.button("Import Data Konsumen"):
                imported, failed = 0, 0
                for _, row in df_import.iterrows():
                    try:
                        n, a, t, pj, j = row.get("nama"), row.get("alamat"), row.get("telp"), row.get("pj"), row.get("jenis_project")
                        cek_duplikat = c.execute(
                            "SELECT id FROM konsumen WHERE nama=? AND telp=? AND jenis_project=?",
                            (n, t, j)
                        ).fetchone()
                        if not cek_duplikat and n and a and t and j:
                            c.execute("INSERT INTO konsumen VALUES (?,?,?,?,?,?)", (gen_id("KS"), n, a, t, pj, j))
                            imported += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                conn.commit()
                st.success(f"✅ {imported} konsumen berhasil diimport, {failed} baris gagal/duplikat")
                st.rerun()
        except Exception as e:
            st.error(f"Error membaca file: {e}")

    st.divider()
    st.subheader("➕ Tambah Konsumen Manual")
    with st.form("add_ks", clear_on_submit=True):
        n = st.text_input("Nama Konsumen")
        a = st.text_input("Alamat")
        t = st.text_input("No Telp")
        pj = st.text_input("PJ")
        j = st.text_input("Jenis Project")

        if st.form_submit_button("Simpan"):
            cek_duplikat = c.execute(
                "SELECT id FROM konsumen WHERE nama=? AND telp=? AND jenis_project=?",
                (n, t, j)
            ).fetchone()

            if not n or not a or not t or not j:
                st.error("Semua kolom wajib diisi!")
            elif cek_duplikat:
                st.error("Data konsumen sudah ada.")
            else:
                try:
                    c.execute("INSERT INTO konsumen VALUES (?,?,?,?,?,?)", (gen_id("KS"), n, a, t, pj, j))
                    conn.commit()
                    st.success(f"Konsumen '{n}' berhasil disimpan!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Terjadi kesalahan: {e}")

    st.divider()
    df = pd.read_sql("SELECT * FROM konsumen", conn)
    edited = st.data_editor(df, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Simpan Perubahan Data", key="btn_save_konsumen"):
            for _, r in edited.iterrows():
                c.execute(
                    "UPDATE konsumen SET nama=?, alamat=?, telp=?, pj=?, jenis_project=? WHERE id=?",
                    (r["nama"], r["alamat"], r["telp"], r["pj"], r["jenis_project"], r["id"])
                )
            conn.commit()
            st.rerun()

    with col2:
        if not df.empty:
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Konsumen")
            buffer.seek(0)
            st.download_button(
                label="📥 Download Excel",
                data=buffer.getvalue(),
                file_name="Master_Konsumen.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# =========================
# MENU 5: ASSIGN PROJECT
# =========================
elif menu == "Assign Project":
    st.title("📋 Penugasan Proyek")

    tk = pd.read_sql("SELECT nama FROM teknisi", conn)
    ks = pd.read_sql("SELECT * FROM konsumen", conn)

    if tk.empty or ks.empty:
        st.warning("Pastikan data Master Teknisi dan Master Konsumen sudah diisi!")
    else:
        with st.form("form_assign", clear_on_submit=True):
            tek = st.selectbox("Pilih Teknisi", tk["nama"])
            pilih_ks = st.selectbox("Pilih Konsumen", ks["nama"].unique())
            project_options = ks[ks["nama"] == pilih_ks]["jenis_project"].tolist()
            pilih_proj = st.selectbox("Pilih Jenis Project", project_options)

            detail_ks = ks[(ks["nama"] == pilih_ks) & (ks["jenis_project"] == pilih_proj)].iloc[0]
            alamat_proyek_default = detail_ks["alamat"]

            alamat_proyek = st.text_input("Alamat Proyek (bisa diubah)", value=alamat_proyek_default)
            st.info(f"📍 Alamat Proyek: **{alamat_proyek}**")

            tgl = str(st.date_input("Tanggal"))
            col_l1, col_l2 = st.columns(2)
            lat_val = col_l1.number_input("Lat", format="%.6f", value=0.0)
            long_val = col_l2.number_input("Long", format="%.6f", value=0.0)

            if st.form_submit_button("Assign"):
                existing = c.execute(
                    "SELECT id FROM assign WHERE nama_teknisi=? AND alamat=? AND tgl=? AND jenis_project=?",
                    (tek, alamat_proyek, tgl, pilih_proj)
                ).fetchone()

                if existing:
                    st.error(f"Gagal: Penugasan sudah ada (ID: {existing[0]}).")
                else:
                    try:
                        c.execute(
                            "INSERT INTO assign VALUES (?,?,?,?,?,?,?,?,?)",
                            (gen_id("PR"), tek, tgl, alamat_proyek, "baru dimulai", lat_val, long_val, pilih_proj, pilih_ks)
                        )
                        conn.commit()
                        st.success(f"Proyek {pilih_proj} di {alamat_proyek} berhasil di-assign ke {tek}!")
                        st.rerun()
                    except sqlite3.IntegrityError as e:
                        st.error(f"Gagal menyimpan: {e}")
                    except Exception as e:
                        st.error(f"Terjadi kesalahan: {e}")

        if st.button("Cari Koordinat dari Alamat"):
            try:
                url = "https://nominatim.openstreetmap.org/search"
                params = {"q": alamat_proyek, "format": "json", "limit": 1}
                headers = {"User-Agent": "Dashboard-Teknisi/1.0"}
                res = requests.get(url, params=params, headers=headers, timeout=10)
                res.raise_for_status()
                data = res.json()

                if not data:
                    st.error("Koordinat tidak ditemukan untuk alamat tersebut.")
                else:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    st.success(f"Ditemukan: lat={lat:.6f}, long={lon:.6f}")
            except Exception as e:
                st.error(f"Gagal melakukan geocoding: {e}")

    st.subheader("📋 Master Progress Proyek")
    df_assign = pd.read_sql("""
        SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama
        FROM assign
        ORDER BY tgl DESC
    """, conn)

    if not df_assign.empty:
        column_config = {
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=["baru dimulai", "mulai", "proses", "done", "perbaikan", "done final", "selesai"]
            )
        }

        edited_assign = st.data_editor(
            df_assign,
            use_container_width=True,
            column_config=column_config,
            hide_index=True
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Simpan Perubahan Status", key="save_assign_status"):
                for _, row in edited_assign.iterrows():
                    new_status = normalize_status(row["status"])
                    c.execute("UPDATE assign SET status=? WHERE id=?", (new_status, row["id"]))
                conn.commit()
                st.success("✅ Status berhasil diperbarui!")
                st.rerun()

        with col2:
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_assign.to_excel(writer, index=False, sheet_name="Penugasan")
            buffer.seek(0)
            st.download_button(
                label="📥 Download Excel",
                data=buffer.getvalue(),
                file_name="Daftar_Penugasan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.info("Belum ada penugasan.")

    st.divider()

    if not df_assign.empty:
        df_assign["label"] = df_assign.apply(
            lambda r: f"{r['id']} | {r['nama_teknisi']} | {r['tgl']} | {r['alamat']}",
            axis=1
        )
        choices = df_assign.set_index("id")["label"].to_dict()
        to_delete = st.multiselect(
            "Pilih penugasan untuk dihapus",
            options=list(choices.keys()),
            format_func=lambda i: choices[i]
        )

        if to_delete:
            if st.checkbox(f"Konfirmasi: hapus {len(to_delete)} penugasan yang dipilih"):
                if st.button("Hapus Terpilih"):
                    moved = 0
                    for _id in to_delete:
                        row = c.execute(
                            "SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama FROM assign WHERE id=?",
                            (_id,)
                        ).fetchone()
                        if row:
                            try:
                                c.execute(
                                    "INSERT OR REPLACE INTO assign_archive VALUES (?,?,?,?,?,?,?,?,?,?)",
                                    (*row, datetime.now().isoformat())
                                )
                            except Exception:
                                pass
                            c.execute("DELETE FROM assign WHERE id=?", (_id,))
                            moved += 1
                    conn.commit()
                    st.success(f"{moved} penugasan dipindahkan ke arsip dan dihapus.")
                    st.rerun()

    df_archive = pd.read_sql("""
        SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, deleted_at, konsumen_nama
        FROM assign_archive
        ORDER BY deleted_at DESC
    """, conn)

    if not df_archive.empty:
        st.subheader("Arsip Penugasan (Restore / Undo)")
        df_archive["label"] = df_archive.apply(
            lambda r: f"{r['id']} | {r['nama_teknisi']} | {r['tgl']} | {r['alamat']} | {r['deleted_at']}",
            axis=1
        )
        archive_choices = df_archive.set_index("id")["label"].to_dict()
        to_restore = st.multiselect(
            "Pilih arsip untuk dikembalikan",
            options=list(archive_choices.keys()),
            format_func=lambda i: archive_choices[i]
        )

        if to_restore:
            if st.checkbox(f"Konfirmasi: restore {len(to_restore)} arsip yang dipilih"):
                if st.button("Restore Terpilih"):
                    restored = 0
                    for _id in to_restore:
                        row = c.execute(
                            "SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama FROM assign_archive WHERE id=?",
                            (_id,)
                        ).fetchone()
                        if row:
                            try:
                                c.execute("INSERT INTO assign VALUES (?,?,?,?,?,?,?,?,?)", row)
                                c.execute("DELETE FROM assign_archive WHERE id=?", (_id,))
                                restored += 1
                            except sqlite3.IntegrityError:
                                st.error(f"Gagal restore {_id}: penugasan serupa sudah ada.")
                    conn.commit()
                    st.success(f"{restored} arsip berhasil dikembalikan ke daftar penugasan.")
                    st.rerun()

# =========================
# MENU 6: UPDATE STATUS
# =========================
elif menu == "Update Status":
    st.title("🔄 Update Status Pengerjaan Proyek")

    df_assign = pd.read_sql("""
        SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama
        FROM assign
        ORDER BY tgl DESC
    """, conn)

    if df_assign.empty:
        st.warning("Belum ada penugasan proyek.")
    else:
        df_assign["status"] = df_assign["status"].apply(normalize_status)

        st.sidebar.subheader("🔍 Filter")
        konsumen_list = ["Semua"] + sorted(df_assign["konsumen_nama"].dropna().unique().tolist())
        selected_konsumen = st.sidebar.selectbox("Pilih Konsumen", konsumen_list)

        if selected_konsumen != "Semua":
            tmp = df_assign[df_assign["konsumen_nama"] == selected_konsumen]
            project_types = ["Semua"] + sorted(tmp["jenis_project"].dropna().unique().tolist())
        else:
            project_types = ["Semua"] + sorted(df_assign["jenis_project"].dropna().unique().tolist())

        selected_jp = st.sidebar.selectbox("Jenis Project", project_types)
        selected_status_filter = st.sidebar.selectbox("Filter Status", ["Semua"] + PROGRESS_FLOW)
        selected_tek_filter = st.sidebar.selectbox("Filter Teknisi", ["Semua"] + sorted(df_assign["nama_teknisi"].dropna().unique().tolist()))

        df_filtered = df_assign.copy()
        if selected_konsumen != "Semua":
            df_filtered = df_filtered[df_filtered["konsumen_nama"] == selected_konsumen]
        if selected_jp != "Semua":
            df_filtered = df_filtered[df_filtered["jenis_project"] == selected_jp]
        if selected_status_filter != "Semua":
            df_filtered = df_filtered[df_filtered["status"] == selected_status_filter]
        if selected_tek_filter != "Semua":
            df_filtered = df_filtered[df_filtered["nama_teknisi"] == selected_tek_filter]

        st.subheader("📊 Ringkasan Status")
        cols = st.columns(len(PROGRESS_FLOW))
        for i, s in enumerate(PROGRESS_FLOW):
            cols[i].metric(f"{STATUS_EMOJI[s]} {s.title()}", int((df_filtered["status"] == s).sum()))

        st.divider()
        st.subheader("📋 Master Progress Project")
        st.caption("Klik tombol ◀ / ▶ untuk mundur atau maju status.")

        if df_filtered.empty:
            st.info("Tidak ada data untuk filter ini.")
        else:
            for _, row in df_filtered.iterrows():
                proj_id = row["id"]
                norm_stat = normalize_status(row["status"])
                color = STATUS_COLOR.get(norm_stat, "#888")
                emoji = STATUS_EMOJI.get(norm_stat, "●")
                is_first = PROGRESS_FLOW.index(norm_stat) == 0
                is_last = PROGRESS_FLOW.index(norm_stat) == len(PROGRESS_FLOW) - 1

                with st.container():
                    h1, h2 = st.columns([5, 1])
                    with h1:
                        st.markdown(
                            f"""
                            **{row['nama_teknisi']}** | `{row['jenis_project']}` | {row['konsumen_nama']}  
                            <small style="color:#aaa">{row['tgl']} · {str(row['alamat'])[:50]}</small>
                            <span style="background:{color};color:white;padding:2px 10px;border-radius:12px;font-size:12px;margin-left:8px;">
                            {emoji} {norm_stat.upper()}
                            </span>
                            """,
                            unsafe_allow_html=True
                        )
                    with h2:
                        st.markdown(f"<small style='color:#888'>{proj_id}</small>", unsafe_allow_html=True)

                    st.markdown(render_progress_bar(norm_stat), unsafe_allow_html=True)

                    btn_cols = st.columns([1, 1, 6])
                    with btn_cols[0]:
                        if not is_first:
                            prev_s = prev_status(norm_stat)
                            if st.button(f"◀ {prev_s.title()}", key=f"prev_{proj_id}", use_container_width=True):
                                c.execute("UPDATE assign SET status=? WHERE id=?", (prev_s, proj_id))
                                conn.commit()
                                st.rerun()
                        else:
                            st.button("◀ Awal", key=f"prev_disabled_{proj_id}", disabled=True, use_container_width=True)

                    with btn_cols[1]:
                        if not is_last:
                            next_s = next_status(norm_stat)
                            if st.button(f"▶ {next_s.title()}", key=f"next_{proj_id}", type="primary", use_container_width=True):
                                c.execute("UPDATE assign SET status=? WHERE id=?", (next_s, proj_id))
                                conn.commit()
                                st.rerun()
                        else:
                            st.button("✅ Selesai", key=f"next_disabled_{proj_id}", disabled=True, use_container_width=True)

                st.divider()

        with st.expander("⚙️ Edit Status Massal via Tabel"):
            st.caption("Ubah kolom Status langsung lalu klik Simpan.")
            df_edit = df_filtered[["id", "nama_teknisi", "konsumen_nama", "jenis_project", "tgl", "alamat", "status"]].copy()
            df_edit = df_edit.rename(columns={
                "nama_teknisi": "Teknisi",
                "konsumen_nama": "Konsumen",
                "jenis_project": "Jenis Project",
                "tgl": "Tanggal",
                "alamat": "Alamat",
                "status": "Status"
            })

            edited_df = st.data_editor(
                df_edit,
                use_container_width=True,
                hide_index=True,
                disabled=["id", "Teknisi", "Konsumen", "Jenis Project", "Tanggal", "Alamat"],
                column_config={
                    "Status": st.column_config.SelectboxColumn("Status", options=PROGRESS_FLOW, required=True)
                },
                key="bulk_status_editor"
            )

            if st.button("💾 Simpan Semua Perubahan", type="primary"):
                changed = 0
                for _, row in edited_df.iterrows():
                    orig_status = df_assign[df_assign["id"] == row["id"]]["status"].values
                    if len(orig_status) > 0:
                        new_status = normalize_status(row["Status"])
                        if orig_status[0] != new_status:
                            c.execute("UPDATE assign SET status=? WHERE id=?", (new_status, row["id"]))
                            changed += 1
                conn.commit()
                if changed:
                    st.success(f"✅ {changed} status diperbarui!")
                    st.rerun()
                else:
                    st.info("Tidak ada perubahan.")

# =========================
# FOOTER
# =========================
st.sidebar.markdown("---")
st.sidebar.caption("Developed by Muhammad Bey Trisnawan")