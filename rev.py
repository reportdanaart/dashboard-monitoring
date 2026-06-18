import re
import random
import sqlite3
from datetime import datetime
from io import BytesIO
from typing import Optional, Tuple

import pandas as pd
import streamlit as st
import plotly.express as px
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

# Optional auto-refresh
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False


# =========================
# CONFIG
# =========================
st.set_page_config(layout="wide", page_title="Dashboard Teknisi")


# =========================
# DATABASE
# =========================
conn = sqlite3.connect("monitoring.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()


# =========================
# GEOCODER
# =========================
geolocator = Nominatim(user_agent="dashboard_teknisi_app")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)


# =========================
# GLOBAL STYLE
# =========================
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 1rem;
    }
    .app-card {
        background: linear-gradient(135deg, #111827, #1f2937);
        padding: 16px 18px;
        border-radius: 16px;
        border: 1px solid rgba(255,255,255,0.08);
        color: white;
        box-shadow: 0 8px 30px rgba(0,0,0,0.15);
    }
    .subtle {
        color: #9ca3af;
        font-size: 0.92rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# HELPERS
# =========================
def clean_value(v):
    if pd.isna(v):
        return None
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v


def normalize_text(v: str) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip()).lower()


def normalize_import_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip().lower() for col in df.columns]
    for col in df.columns:
        df[col] = df[col].apply(clean_value)
    return df


def gen_id(prefix: str) -> str:
    for _ in range(10):
        new_id = f"{prefix}{random.randint(100000, 999999)}"
        exists = c.execute(
            """
            SELECT 1 FROM teknisi WHERE id=?
            UNION
            SELECT 1 FROM konsumen WHERE id=?
            UNION
            SELECT 1 FROM assign WHERE id=?
            UNION
            SELECT 1 FROM assign_archive WHERE id=?
            """,
            (new_id, new_id, new_id, new_id),
        ).fetchone()
        if not exists:
            return new_id
    return f"{prefix}{int(datetime.now().timestamp() * 1000)}"


def export_dataframe(df: pd.DataFrame, filename: str, sheet_name: str):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    buffer.seek(0)
    st.download_button(
        label="📥 Download Excel",
        data=buffer.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def validate_phone(phone: str) -> bool:
    if not phone:
        return False
    phone = re.sub(r"[\s\-]", "", phone)
    return bool(re.fullmatch(r"(\+62|62|0)[0-9]{8,13}", phone))


def normalize_phone(phone: str) -> str:
    return re.sub(r"[\s\-]", "", phone or "")


def ensure_table(create_sql: str):
    c.execute(create_sql)
    conn.commit()


def ensure_column(table_name: str, column_name: str, column_type: str):
    cols = pd.read_sql(f"PRAGMA table_info({table_name})", conn)
    if column_name not in cols["name"].tolist():
        c.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        conn.commit()


def ensure_index():
    c.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_assign_unique
        ON assign (nama_teknisi, alamat_project, tgl, jenis_project, konsumen_id)
        """
    )
    conn.commit()


# =========================
# TABLES
# =========================
ensure_table(
    """
    CREATE TABLE IF NOT EXISTS teknisi (
        id TEXT PRIMARY KEY,
        nama TEXT NOT NULL,
        alamat TEXT NOT NULL,
        telp TEXT NOT NULL,
        area TEXT NOT NULL
    )
    """
)

ensure_table(
    """
    CREATE TABLE IF NOT EXISTS konsumen (
        id TEXT PRIMARY KEY,
        nama TEXT NOT NULL,
        alamat TEXT NOT NULL,
        telp TEXT NOT NULL,
        pj TEXT NOT NULL,
        jenis_project TEXT NOT NULL
    )
    """
)

ensure_table(
    """
    CREATE TABLE IF NOT EXISTS assign (
        id TEXT PRIMARY KEY,
        nama_teknisi TEXT NOT NULL,
        tgl TEXT NOT NULL,
        alamat TEXT NOT NULL,
        status TEXT NOT NULL,
        lat REAL,
        long REAL,
        jenis_project TEXT NOT NULL,
        konsumen_nama TEXT NOT NULL,
        alamat_konsumen TEXT,
        alamat_project TEXT,
        konsumen_id TEXT
    )
    """
)

ensure_table(
    """
    CREATE TABLE IF NOT EXISTS assign_archive (
        id TEXT PRIMARY KEY,
        nama_teknisi TEXT NOT NULL,
        tgl TEXT NOT NULL,
        alamat TEXT NOT NULL,
        status TEXT NOT NULL,
        lat REAL,
        long REAL,
        jenis_project TEXT NOT NULL,
        deleted_at TEXT NOT NULL,
        konsumen_nama TEXT NOT NULL,
        alamat_konsumen TEXT,
        alamat_project TEXT,
        konsumen_id TEXT
    )
    """
)

ensure_column("assign", "alamat_konsumen", "TEXT")
ensure_column("assign", "alamat_project", "TEXT")
ensure_column("assign", "konsumen_id", "TEXT")
ensure_column("assign_archive", "alamat_konsumen", "TEXT")
ensure_column("assign_archive", "alamat_project", "TEXT")
ensure_column("assign_archive", "konsumen_id", "TEXT")
ensure_index()

# Backfill old rows
c.execute(
    """
    UPDATE assign
    SET alamat_konsumen = COALESCE(alamat_konsumen, alamat),
        alamat_project = COALESCE(alamat_project, alamat)
    """
)
c.execute(
    """
    UPDATE assign_archive
    SET alamat_konsumen = COALESCE(alamat_konsumen, alamat),
        alamat_project = COALESCE(alamat_project, alamat)
    """
)
conn.commit()


# =========================
# DATA MIGRATION
# =========================
def sync_assign_names_from_konsumen():
    rows = c.execute(
        """
        SELECT id, konsumen_id
        FROM assign
        WHERE konsumen_id IS NOT NULL AND konsumen_id != ''
        """
    ).fetchall()

    updated = 0
    for row in rows:
        kons = c.execute(
            "SELECT nama, alamat, jenis_project FROM konsumen WHERE id = ?",
            (row["konsumen_id"],),
        ).fetchone()
        if kons:
            c.execute(
                """
                UPDATE assign
                SET konsumen_nama = ?,
                    jenis_project = ?
                WHERE id = ?
                """,
                (kons["nama"], kons["jenis_project"], row["id"]),
            )
            updated += 1

    conn.commit()
    return updated


def migrate_old_assign_konsumen_id():
    rows = c.execute(
        """
        SELECT id, konsumen_nama, alamat_konsumen, jenis_project, konsumen_id
        FROM assign
        WHERE konsumen_id IS NULL OR konsumen_id = ''
        """
    ).fetchall()

    updated = 0
    for row in rows:
        kandidat = c.execute(
            """
            SELECT id
            FROM konsumen
            WHERE LOWER(TRIM(nama)) = LOWER(TRIM(?))
              AND LOWER(TRIM(jenis_project)) = LOWER(TRIM(?))
            LIMIT 1
            """,
            (row["konsumen_nama"] or "", row["jenis_project"] or ""),
        ).fetchone()

        if kandidat:
            c.execute("UPDATE assign SET konsumen_id=? WHERE id=?", (kandidat["id"], row["id"]))
            updated += 1

    conn.commit()
    return updated


migrate_old_assign_konsumen_id()
sync_assign_names_from_konsumen()


# =========================
# GEOCODE CACHE
# =========================
def ensure_geocode_cache_table():
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
            address TEXT PRIMARY KEY,
            lat REAL,
            lon REAL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


ensure_geocode_cache_table()


def get_geocode_from_db(address: str) -> Tuple[Optional[float], Optional[float]]:
    row = c.execute(
        "SELECT lat, lon FROM geocode_cache WHERE address = ?",
        (normalize_text(address),),
    ).fetchone()
    if row:
        return row["lat"], row["lon"]
    return None, None


def save_geocode_to_db(address: str, lat: float, lon: float):
    c.execute(
        """
        INSERT OR REPLACE INTO geocode_cache (address, lat, lon, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (normalize_text(address), float(lat), float(lon), datetime.now().isoformat()),
    )
    conn.commit()


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def geocode_address_cached(address: str) -> Tuple[Optional[float], Optional[float]]:
    if not address or not str(address).strip():
        return None, None

    address_norm = normalize_text(address)
    db_lat, db_lon = get_geocode_from_db(address_norm)
    if db_lat is not None and db_lon is not None:
        return float(db_lat), float(db_lon)

    try:
        location = geocode(address)
        if location:
            lat, lon = float(location.latitude), float(location.longitude)
            save_geocode_to_db(address_norm, lat, lon)
            return lat, lon
    except Exception:
        pass

    return None, None


def geocode_address(address: str):
    return geocode_address_cached(address)


# =========================
# STATUS
# =========================
def normalize_status(s):
    flow = ["mulai", "proses", "done", "perbaikan", "done final"]
    alias = {
        "baru dimulai": "mulai",
        "selesai": "done",
        "finish": "done final",
        "done final": "done final",
    }
    s = normalize_text(s)
    return alias.get(s, s if s in flow else "mulai")


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
    items = []

    for i, step in enumerate(PROGRESS_FLOW):
        if i < idx:
            dot_style = f"background:{STATUS_COLOR[step]};color:white;border:2px solid {STATUS_COLOR[step]};"
            dot_text = "✓"
        elif i == idx:
            dot_style = f"background:{STATUS_COLOR[step]};color:white;border:3px solid white;box-shadow:0 0 0 2px {STATUS_COLOR[step]};"
            dot_text = STATUS_EMOJI.get(step, "●")
        else:
            dot_style = "background:#444;color:#888;border:2px solid #555;"
            dot_text = str(i + 1)

        items.append(
            f"""
            <div style="display:flex;flex-direction:column;align-items:center;flex:1;">
                <div style="width:28px;height:28px;border-radius:50%;{dot_style}display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:bold;">
                    {dot_text}
                </div>
                <div style="font-size:10px;margin-top:4px;text-align:center;color:#ddd;font-weight:600;">{step.upper()}</div>
            </div>
            """
        )
        if i < len(PROGRESS_FLOW) - 1:
            line_color = STATUS_COLOR[step] if i < idx else "#444"
            items.append(f'<div style="flex:0.5;height:3px;background:{line_color};margin-top:13px;"></div>')

    return f"""
    <div style="background:#1a1a2e;border-radius:10px;padding:10px 16px 6px;margin-bottom:6px;">
        <div style="display:flex;align-items:flex-start;width:100%;">{''.join(items)}</div>
    </div>
    """


BRIGHT_PALETTE = [
    "#FF6B6B", "#4D96FF", "#6BCB77", "#FFD93D", "#FF8FAB",
    "#845EC2", "#00C9A7", "#F9C74F", "#F3722C", "#43AA8B",
    "#577590", "#F94144", "#90BE6D", "#00B4D8", "#F8961E",
]


def get_color_map(values):
    uniq = [v for v in pd.Series(values).dropna().astype(str).unique().tolist()]
    return {v: BRIGHT_PALETTE[i % len(BRIGHT_PALETTE)] for i, v in enumerate(sorted(uniq))}


def build_folium_map(df: pd.DataFrame):
    df = df.copy()
    if "lat" not in df.columns or "long" not in df.columns:
        return None, {}, {}

    df = df[df["lat"].notna() & df["long"].notna()]
    if df.empty:
        return None, {}, {}

    konsumen_colors = get_color_map(df.get("konsumen_nama", []))
    teknisi_colors = get_color_map(df.get("nama_teknisi", []))

    center_lat = float(df["lat"].mean())
    center_lon = float(df["long"].mean())

    m = folium.Map(location=[center_lat, center_lon], zoom_start=6, tiles="OpenStreetMap")

    for teknisi_name, group in df.groupby("nama_teknisi"):
        color = teknisi_colors.get(str(teknisi_name), "#4D96FF")
        feature_group = folium.FeatureGroup(name=f"Teknisi: {teknisi_name}", show=True)
        cluster = MarkerCluster(name=f"Cluster {teknisi_name}")

        for _, row in group.iterrows():
            popup_html = f"""
            <b>Konsumen:</b> {row.get('konsumen_nama', '-') }<br>
            <b>Teknisi:</b> {row.get('nama_teknisi', '-') }<br>
            <b>Jenis:</b> {row.get('jenis_project', '-') }<br>
            <b>Status:</b> {row.get('status', '-') }<br>
            <b>Alamat Project:</b> {row.get('alamat_project', '-') }<br>
            <b>Tanggal:</b> {row.get('tgl', '-') }
            """
            folium.Marker(
                location=[float(row["lat"]), float(row["long"])],
                popup=folium.Popup(popup_html, max_width=350),
                tooltip=f"{row.get('konsumen_nama', '-') } - {row.get('status', '-') }",
                icon=folium.Icon(color="blue", icon="wrench", prefix="fa"),
            ).add_to(cluster)

            folium.CircleMarker(
                location=[float(row["lat"]), float(row["long"])],
                radius=7,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                weight=2,
            ).add_to(feature_group)

        cluster.add_to(feature_group)
        feature_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m, konsumen_colors, teknisi_colors


def delete_rows_with_dat_editor(df: pd.DataFrame, key_prefix: str, delete_callback, checkbox_label: str = "Hapus"):
    if df.empty:
        st.info("Tidak ada data.")
        return

    editor_df = df.copy()
    editor_df.insert(0, checkbox_label, False)
    edited_df = st.data_editor(
        editor_df,
        use_container_width=True,
        hide_index=True,
        height=min(420, 38 + 35 * max(len(editor_df), 1)),
        disabled=[col for col in editor_df.columns if col != checkbox_label],
        column_config={
            checkbox_label: st.column_config.CheckboxColumn(
                checkbox_label,
                help="Centang baris yang ingin dipilih",
                width="small",
            )
        },
        key=f"{key_prefix}_editor",
    )
    to_delete = edited_df[edited_df[checkbox_label] == True].drop(columns=[checkbox_label])

    if st.button("🗑️ Hapus Terpilih", key=f"{key_prefix}_delete_btn", type="primary"):
        if to_delete.empty:
            st.info("Belum ada baris yang dipilih untuk dihapus.")
            return
        delete_callback(to_delete)
        st.rerun()


def restore_rows_with_dat_editor(df: pd.DataFrame, key_prefix: str, restore_callback, checkbox_label: str = "Restore"):
    if df.empty:
        st.info("Tidak ada data arsip.")
        return

    editor_df = df.copy()
    editor_df.insert(0, checkbox_label, False)
    edited_df = st.data_editor(
        editor_df,
        use_container_width=True,
        hide_index=True,
        height=min(420, 38 + 35 * max(len(editor_df), 1)),
        disabled=[col for col in editor_df.columns if col != checkbox_label],
        column_config={
            checkbox_label: st.column_config.CheckboxColumn(checkbox_label, width="small")
        },
        key=f"{key_prefix}_editor",
    )
    to_restore = edited_df[edited_df[checkbox_label] == True].drop(columns=[checkbox_label])

    if st.button("♻️ Restore Terpilih", key=f"{key_prefix}_restore_btn", type="primary"):
        if to_restore.empty:
            st.info("Belum ada baris yang dipilih untuk dikembalikan.")
            return
        restore_callback(to_restore)
        st.rerun()


# =========================
# MASTER DATA
# =========================
def get_konsumen_options():
    return pd.read_sql(
        """
        SELECT id, nama, alamat, telp, pj, jenis_project
        FROM konsumen
        ORDER BY nama, jenis_project, alamat
        """,
        conn,
    )


def get_konsumen_project_options(konsumen_id: str):
    df = pd.read_sql(
        """
        SELECT DISTINCT jenis_project
        FROM konsumen
        WHERE id = ? AND jenis_project IS NOT NULL
        ORDER BY jenis_project
        """,
        conn,
        params=(konsumen_id,),
    )
    return df["jenis_project"].dropna().tolist() if not df.empty else []


def get_konsumen_addresses(konsumen_id: str, jenis_project: str | None = None):
    if jenis_project:
        df = pd.read_sql(
            """
            SELECT DISTINCT alamat
            FROM konsumen
            WHERE id = ? AND jenis_project = ? AND alamat IS NOT NULL
            ORDER BY alamat
            """,
            conn,
            params=(konsumen_id, jenis_project),
        )
    else:
        df = pd.read_sql(
            """
            SELECT DISTINCT alamat
            FROM konsumen
            WHERE id = ? AND alamat IS NOT NULL
            ORDER BY alamat
            """,
            conn,
            params=(konsumen_id,),
        )
    return df["alamat"].dropna().tolist() if not df.empty else []


def konsumen_exists(nama: str, telp: str, jenis_project: str, alamat: str, exclude_id: str | None = None) -> bool:
    query = """
        SELECT id FROM konsumen
        WHERE LOWER(TRIM(nama)) = LOWER(TRIM(?))
          AND telp = ?
          AND LOWER(TRIM(jenis_project)) = LOWER(TRIM(?))
          AND LOWER(TRIM(alamat)) = LOWER(TRIM(?))
    """
    params = [nama, telp, jenis_project, alamat]
    if exclude_id:
        query += " AND id != ?"
        params.append(exclude_id)
    return c.execute(query, params).fetchone() is not None


def sync_assign_after_konsumen_update(konsumen_id: str):
    kons = c.execute(
        "SELECT nama, jenis_project FROM konsumen WHERE id=?",
        (konsumen_id,),
    ).fetchone()
    if not kons:
        return

    c.execute(
        """
        UPDATE assign
        SET konsumen_nama = ?,
            jenis_project = ?
        WHERE konsumen_id = ?
        """,
        (kons["nama"], kons["jenis_project"], konsumen_id),
    )
    conn.commit()


# =========================
# NAVIGATION
# =========================
st.sidebar.title("🚀 Navigasi")
menu = st.sidebar.radio(
    "Menu Utama",
    [
        "Monitoring Project",
        "Analytics Dashboard",
        "Master Teknisi",
        "Master Konsumen",
        "Assign Project",
        "Update Status",
    ],
)


# =========================
# MENU 1
# =========================
if menu == "Monitoring Project":
    st.title("📈 Monitoring Project")

    if HAS_AUTOREFRESH:
        st_autorefresh(interval=15000, key="monitor_auto_refresh")

    df = pd.read_sql(
        """
        SELECT id, nama_teknisi, tgl, alamat_project AS alamat, status, lat, long, jenis_project, konsumen_nama, alamat_project
        FROM assign
        ORDER BY tgl DESC
        """,
        conn,
    )

    if df.empty:
        st.info("Belum ada data pengerjaan.")
    else:
        df["nama_konsumen"] = df["konsumen_nama"]
        df["tgl_dt"] = pd.to_datetime(df["tgl"], errors="coerce")
        df["status_norm"] = df["status"].apply(normalize_status)

        st.sidebar.subheader("Filter Monitoring")
        tek = st.sidebar.selectbox("Filter Teknisi", ["Semua"] + df["nama_teknisi"].dropna().unique().tolist())
        ks = st.sidebar.selectbox("Filter Konsumen", ["Semua"] + df["nama_konsumen"].fillna("N/A").unique().tolist())
        jp = st.sidebar.selectbox("Filter Jenis Project", ["Semua"] + df["jenis_project"].dropna().unique().tolist())

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

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Tugas", len(filtered))
        c2.metric("Teknisi Aktif", filtered["nama_teknisi"].nunique())
        c3.metric("Konsumen", filtered["nama_konsumen"].nunique())

        st.subheader("🗺️ Map Monitoring Project")
        m, _, _ = build_folium_map(filtered)
        if m:
            st_folium(m, width=None, height=600)
        else:
            st.info("Belum ada titik lokasi valid untuk ditampilkan di map.")

        st.subheader("📋 Data Monitoring")
        st.dataframe(filtered, use_container_width=True, hide_index=True)

        if not filtered.empty:
            export_dataframe(filtered, "Monitoring_Project.xlsx", "Monitoring")


# =========================
# MENU 2
# =========================
elif menu == "Analytics Dashboard":
    st.title("📊 Analytics Dashboard Profesional")

    df_all = pd.read_sql(
        """
        SELECT id, nama_teknisi, tgl, alamat_project AS alamat, status, lat, long, jenis_project, konsumen_nama
        FROM assign
        ORDER BY tgl DESC
        """,
        conn,
    )

    if df_all.empty:
        st.info("Belum ada data penugasan untuk dianalisis.")
    else:
        df_all["status_norm"] = df_all["status"].apply(normalize_status)
        total_projects = len(df_all)
        total_done = (df_all["status_norm"] == "done").sum()
        total_in_progress = df_all["status_norm"].isin(["mulai", "proses", "perbaikan"]).sum()
        completion_rate = (total_done / total_projects * 100) if total_projects else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Proyek", total_projects)
        c2.metric("✅ Selesai", int(total_done))
        c3.metric("⏳ Proses", int(total_in_progress))
        c4.metric("📊 Completion Rate", f"{completion_rate:.1f}%")

        st.divider()

        status_counts = df_all["status_norm"].value_counts()
        left, right = st.columns(2)
        with left:
            fig_pie = px.pie(values=status_counts.values, names=status_counts.index, title="Status Penugasan")
            st.plotly_chart(fig_pie, use_container_width=True)
        with right:
            status_df = pd.DataFrame({"Status": status_counts.index, "Jumlah": status_counts.values})
            fig_bar = px.bar(status_df, x="Status", y="Jumlah", title="Jumlah Proyek per Status", text_auto=True)
            st.plotly_chart(fig_bar, use_container_width=True)

        st.divider()
        teknisi_stats = df_all.groupby("nama_teknisi").agg(
            **{
                "Total Proyek": ("id", "count"),
                "Selesai": ("status_norm", lambda x: (x == "done").sum()),
            }
        )
        teknisi_stats["% Completion"] = (teknisi_stats["Selesai"] / teknisi_stats["Total Proyek"] * 100).round(2)
        teknisi_stats = teknisi_stats.sort_values("Total Proyek", ascending=False)
        st.dataframe(teknisi_stats.reset_index(), use_container_width=True, hide_index=True)


# =========================
# MENU 3
# =========================
elif menu == "Master Teknisi":
    st.title("👨‍🔧 Master Teknisi")

    search = st.text_input("🔍 Search Teknisi")
    uploaded_file = st.file_uploader("Upload Excel (nama, alamat, telp, area)", type=["xlsx", "xls"])

    if uploaded_file is not None:
        try:
            df_import = normalize_import_dataframe(pd.read_excel(uploaded_file))
            st.dataframe(df_import, use_container_width=True, hide_index=True)

            if st.button("Import Data Teknisi"):
                required_cols = {"nama", "alamat", "telp", "area"}
                missing = required_cols - set(df_import.columns)
                if missing:
                    st.error(f"Kolom wajib tidak ditemukan: {', '.join(missing)}")
                else:
                    imported, failed = 0, 0
                    for _, row in df_import.iterrows():
                        try:
                            n = clean_value(row.get("nama"))
                            a = clean_value(row.get("alamat"))
                            t = normalize_phone(clean_value(row.get("telp")) or "")
                            ar = clean_value(row.get("area"))

                            if not all([n, a, t, ar]) or not validate_phone(t):
                                failed += 1
                                continue

                            cek_nama = c.execute(
                                "SELECT id FROM teknisi WHERE LOWER(TRIM(nama))=LOWER(TRIM(?))",
                                (n,),
                            ).fetchone()
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
    st.subheader("➕ Tambah / Edit Teknisi")
    df_tk = pd.read_sql("SELECT * FROM teknisi ORDER BY nama", conn)
    if search:
        mask = df_tk.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False))
        df_tk = df_tk[mask.any(axis=1)]

    if not df_tk.empty:
        st.dataframe(df_tk, use_container_width=True, hide_index=True)

        edit_id = st.selectbox("Pilih Teknisi untuk Edit", [""] + df_tk["id"].tolist())
        if edit_id:
            row = pd.read_sql("SELECT * FROM teknisi WHERE id=?", conn, params=(edit_id,)).iloc[0]
            with st.form("edit_teknisi"):
                n = st.text_input("Nama", value=row["nama"])
                a = st.text_input("Alamat", value=row["alamat"])
                t = st.text_input("No Telp", value=row["telp"])
                ar = st.text_input("Area", value=row["area"])
                submit_edit = st.form_submit_button("Update")

            if submit_edit:
                t = normalize_phone(t)
                if not all([n.strip(), a.strip(), t.strip(), ar.strip()]):
                    st.error("Semua field wajib diisi.")
                elif not validate_phone(t):
                    st.error("Format nomor telepon tidak valid.")
                else:
                    cek_nama = c.execute(
                        "SELECT id FROM teknisi WHERE LOWER(TRIM(nama))=LOWER(TRIM(?)) AND id != ?",
                        (n, edit_id),
                    ).fetchone()
                    cek_telp = c.execute("SELECT id FROM teknisi WHERE telp=? AND id != ?", (t, edit_id)).fetchone()
                    if cek_nama:
                        st.error(f"Nama '{n}' sudah terdaftar.")
                    elif cek_telp:
                        st.error(f"No Telp '{t}' sudah digunakan.")
                    else:
                        c.execute(
                            "UPDATE teknisi SET nama=?, alamat=?, telp=?, area=? WHERE id=?",
                            (n, a, t, ar, edit_id),
                        )
                        conn.commit()
                        st.success("Data teknisi berhasil diupdate.")
                        st.rerun()

    st.subheader("🗑️ Hapus Teknisi")

    def delete_teknisi_callback(to_delete_df: pd.DataFrame):
        deleted = 0
        blocked = []
        for _, row in to_delete_df.iterrows():
            _id = row["id"]
            name = row["nama"]
            assign_count = c.execute(
                "SELECT COUNT(*) FROM assign WHERE nama_teknisi=?",
                (name,),
            ).fetchone()[0]
            if assign_count > 0:
                blocked.append((name, assign_count))
                continue
            c.execute("DELETE FROM teknisi WHERE id=?", (_id,))
            deleted += 1
        conn.commit()
        if deleted:
            st.success(f"{deleted} teknisi berhasil dihapus.")
        if blocked:
            st.error(
                "Tidak dapat menghapus teknisi yang masih memiliki penugasan: "
                + ", ".join([f"{n} ({cnt})" for n, cnt in blocked])
            )

    delete_rows_with_dat_editor(df_tk, "teknisi", delete_teknisi_callback)

    with st.form("add_tk", clear_on_submit=True):
        n = st.text_input("Nama")
        a = st.text_input("Alamat")
        t = st.text_input("No Telp")
        ar = st.text_input("Area")
        submitted = st.form_submit_button("Simpan")

    if submitted:
        t = normalize_phone(t)
        if not all([n.strip(), a.strip(), t.strip(), ar.strip()]):
            st.error("Semua field wajib diisi.")
        elif not validate_phone(t):
            st.error("Format nomor telepon tidak valid.")
        else:
            cek_nama = c.execute(
                "SELECT id FROM teknisi WHERE LOWER(TRIM(nama))=LOWER(TRIM(?))",
                (n,),
            ).fetchone()
            cek_telp = c.execute("SELECT id FROM teknisi WHERE telp=?", (t,)).fetchone()

            if cek_nama:
                st.error(f"Nama '{n}' sudah terdaftar.")
            elif cek_telp:
                st.error(f"No Telp '{t}' sudah digunakan.")
            else:
                c.execute("INSERT INTO teknisi VALUES (?,?,?,?,?)", (gen_id("TK"), n, a, t, ar))
                conn.commit()
                st.success("Teknisi berhasil ditambahkan!")
                st.rerun()


# =========================
# MENU 4
# =========================
elif menu == "Master Konsumen":
    st.title("🏢 Master Konsumen")

    search = st.text_input("🔍 Search Konsumen")
    uploaded_file = st.file_uploader("Upload Excel (nama, alamat, telp, pj, jenis_project)", type=["xlsx", "xls"])

    if uploaded_file is not None:
        try:
            df_import = normalize_import_dataframe(pd.read_excel(uploaded_file))
            st.dataframe(df_import, use_container_width=True, hide_index=True)

            if st.button("Import Data Konsumen"):
                required_cols = {"nama", "alamat", "telp", "pj", "jenis_project"}
                missing = required_cols - set(df_import.columns)
                if missing:
                    st.error(f"Kolom wajib tidak ditemukan: {', '.join(missing)}")
                else:
                    imported, failed = 0, 0
                    for _, row in df_import.iterrows():
                        try:
                            n = clean_value(row.get("nama"))
                            a = clean_value(row.get("alamat"))
                            t = normalize_phone(clean_value(row.get("telp")) or "")
                            pj = clean_value(row.get("pj"))
                            j = clean_value(row.get("jenis_project"))

                            if not all([n, a, t, pj, j]) or not validate_phone(t):
                                failed += 1
                                continue

                            cek_duplikat = c.execute(
                                """
                                SELECT id FROM konsumen
                                WHERE LOWER(TRIM(nama))=LOWER(TRIM(?))
                                  AND telp=?
                                  AND LOWER(TRIM(jenis_project))=LOWER(TRIM(?))
                                  AND LOWER(TRIM(alamat))=LOWER(TRIM(?))
                                """,
                                (n, t, j, a),
                            ).fetchone()

                            if not cek_duplikat:
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
    st.subheader("➕ Tambah / Edit Konsumen")
    df_ks = pd.read_sql("SELECT * FROM konsumen ORDER BY nama", conn)
    if search:
        mask = df_ks.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False))
        df_ks = df_ks[mask.any(axis=1)]

    if not df_ks.empty:
        st.dataframe(df_ks, use_container_width=True, hide_index=True)

        edit_id = st.selectbox("Pilih Konsumen untuk Edit", [""] + df_ks["id"].tolist())
        if edit_id:
            row = pd.read_sql("SELECT * FROM konsumen WHERE id=?", conn, params=(edit_id,)).iloc[0]
            with st.form("edit_konsumen"):
                n = st.text_input("Nama", value=row["nama"])
                a = st.text_input("Alamat", value=row["alamat"])
                t = st.text_input("No Telp", value=row["telp"])
                pj = st.text_input("PJ", value=row["pj"])
                j = st.text_input("Jenis Project", value=row["jenis_project"])
                submit_edit = st.form_submit_button("Update")

            if submit_edit:
                t = normalize_phone(t)
                if not all([n.strip(), a.strip(), t.strip(), pj.strip(), j.strip()]):
                    st.error("Semua field wajib diisi!")
                elif not validate_phone(t):
                    st.error("Format nomor telepon tidak valid.")
                else:
                    if konsumen_exists(n, t, j, a, exclude_id=edit_id):
                        st.error("Data konsumen duplikat.")
                    else:
                        c.execute(
                            "UPDATE konsumen SET nama=?, alamat=?, telp=?, pj=?, jenis_project=? WHERE id=?",
                            (n, a, t, pj, j, edit_id),
                        )
                        conn.commit()

                        # Sinkronkan semua assign yang terkait dengan konsumen ini
                        sync_assign_after_konsumen_update(edit_id)

                        st.success("Data konsumen berhasil diupdate dan assign terkait ikut disinkronkan.")
                        st.rerun()

    st.subheader("🗑️ Hapus Konsumen")

    def delete_konsumen_callback(to_delete_df: pd.DataFrame):
        deleted = 0
        blocked = []
        for _, row in to_delete_df.iterrows():
            _id = row["id"]
            name = row["nama"]
            assign_count = c.execute(
                "SELECT COUNT(*) FROM assign WHERE konsumen_id=?",
                (_id,),
            ).fetchone()[0]
            if assign_count > 0:
                blocked.append((name, assign_count))
                continue
            c.execute("DELETE FROM konsumen WHERE id=?", (_id,))
            deleted += 1
        conn.commit()
        if deleted:
            st.success(f"{deleted} konsumen berhasil dihapus.")
        if blocked:
            st.error(
                "Tidak dapat menghapus konsumen yang masih memiliki penugasan: "
                + ", ".join([f"{n} ({cnt})" for n, cnt in blocked])
            )

    delete_rows_with_dat_editor(df_ks, "konsumen", delete_konsumen_callback)

    with st.form("add_ks", clear_on_submit=True):
        n = st.text_input("Nama Konsumen")
        a = st.text_input("Alamat")
        t = st.text_input("No Telp")
        pj = st.text_input("PJ")
        j = st.text_input("Jenis Project")
        submitted = st.form_submit_button("Simpan")

    if submitted:
        t = normalize_phone(t)
        if not all([n.strip(), a.strip(), t.strip(), pj.strip(), j.strip()]):
            st.error("Semua field wajib diisi!")
        elif not validate_phone(t):
            st.error("Format nomor telepon tidak valid.")
        else:
            if konsumen_exists(n, t, j, a):
                st.error("Data konsumen sudah ada.")
            else:
                c.execute("INSERT INTO konsumen VALUES (?,?,?,?,?,?)", (gen_id("KS"), n, a, t, pj, j))
                conn.commit()
                st.success(f"Konsumen '{n}' berhasil disimpan!")
                st.rerun()


# =========================
# MENU 5
# =========================
elif menu == "Assign Project":
    st.title("📋 Penugasan Proyek")

    tk = pd.read_sql("SELECT nama FROM teknisi ORDER BY nama", conn)
    ks_df = get_konsumen_options()

    if tk.empty or ks_df.empty:
        st.warning("Pastikan data Master Teknisi dan Master Konsumen sudah diisi!")
    else:
        ks_df["label"] = ks_df.apply(
            lambda row: f"{row['nama']} | {row['jenis_project']} | {row['alamat']} | {row['id']}",
            axis=1,
        )
        konsumen_map = dict(zip(ks_df["label"], ks_df["id"]))
        ks_labels = ks_df["label"].tolist()

        tek = st.selectbox("Pilih Teknisi", tk["nama"].tolist(), key="assign_teknisi")
        pilih_label_ks = st.selectbox("Pilih Konsumen", ks_labels, key="assign_konsumen")
        konsumen_id = konsumen_map[pilih_label_ks]
        konsumen_row = ks_df[ks_df["id"] == konsumen_id].iloc[0]

        project_options = get_konsumen_project_options(konsumen_id)
        if not project_options:
            st.warning("Konsumen ini belum punya jenis project di master.")
            pilih_proj = st.text_input("Jenis Project", key=f"assign_project_text_{konsumen_id}")
        else:
            pilih_proj = st.selectbox(
                "Pilih Jenis Project",
                project_options,
                key=f"assign_project_{konsumen_id}",
            )

        alamat_konsumen_options = get_konsumen_addresses(konsumen_id, pilih_proj if project_options else None)
        if not alamat_konsumen_options:
            alamat_konsumen = st.text_input("Alamat Konsumen", key=f"assign_alamat_konsumen_{konsumen_id}")
        else:
            default_addr = konsumen_row["alamat"] if konsumen_row["alamat"] in alamat_konsumen_options else alamat_konsumen_options[0]
            idx_addr = alamat_konsumen_options.index(default_addr) if default_addr in alamat_konsumen_options else 0
            alamat_konsumen = st.selectbox("Alamat Konsumen", alamat_konsumen_options, index=idx_addr, key=f"assign_alamat_konsumen_{konsumen_id}")

        default_project_address = alamat_konsumen if alamat_konsumen else ""
        alamat_project = st.text_input("Alamat Project / Lokasi Penugasan", value=default_project_address, key=f"assign_project_address_{konsumen_id}")

        tgl = st.date_input("Tanggal", key="assign_tgl")

        auto_lat, auto_long = None, None
        if alamat_project.strip():
            auto_lat, auto_long = geocode_address(alamat_project)

        col_l1, col_l2 = st.columns(2)
        lat_val = col_l1.number_input("Latitude", format="%.6f", value=float(auto_lat) if auto_lat is not None else 0.0, key=f"assign_lat_{konsumen_id}")
        long_val = col_l2.number_input("Longitude", format="%.6f", value=float(auto_long) if auto_long is not None else 0.0, key=f"assign_long_{konsumen_id}")

        with st.form("form_assign", clear_on_submit=True):
            submit = st.form_submit_button("Assign")

        if submit:
            final_alamat_konsumen = alamat_konsumen.strip() if alamat_konsumen else ""
            final_alamat_project = alamat_project.strip() if alamat_project.strip() else final_alamat_konsumen

            if not all([tek.strip(), pilih_label_ks.strip(), pilih_proj.strip(), final_alamat_project]):
                st.error("Semua field assign harus diisi.")
            else:
                tgl_str = str(tgl)
                existing = c.execute(
                    """
                    SELECT id FROM assign
                    WHERE nama_teknisi=? AND alamat_project=? AND tgl=? AND jenis_project=? AND konsumen_id=?
                    """,
                    (tek, final_alamat_project, tgl_str, pilih_proj, konsumen_id),
                ).fetchone()

                if existing:
                    st.error(f"Gagal: Penugasan sudah ada (ID: {existing[0]}).")
                else:
                    lat_to_save = float(auto_lat) if auto_lat is not None else float(lat_val)
                    long_to_save = float(auto_long) if auto_long is not None else float(long_val)

                    c.execute(
                        """
                        INSERT INTO assign
                        (id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama, alamat_konsumen, alamat_project, konsumen_id)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            gen_id("PR"),
                            tek,
                            tgl_str,
                            final_alamat_project,
                            "baru dimulai",
                            lat_to_save,
                            long_to_save,
                            pilih_proj,
                            konsumen_row["nama"],
                            final_alamat_konsumen,
                            final_alamat_project,
                            konsumen_id,
                        ),
                    )
                    conn.commit()
                    st.success(f"Proyek {pilih_proj} di {final_alamat_project} berhasil di-assign ke {tek}!")
                    st.rerun()

        st.subheader("📋 Master Progress Proyek")
        df_assign = pd.read_sql(
            """
            SELECT id, nama_teknisi, tgl, alamat_konsumen, alamat_project, status, lat, long, jenis_project, konsumen_nama, konsumen_id
            FROM assign
            ORDER BY tgl DESC
            """,
            conn,
        )

        if not df_assign.empty:
            st.dataframe(df_assign, use_container_width=True, hide_index=True)

            def delete_assign_callback(to_delete_df):
                moved = 0
                for _, row in to_delete_df.iterrows():
                    _id = row["id"]
                    db_row = c.execute(
                        """
                        SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama, alamat_konsumen, alamat_project, konsumen_id
                        FROM assign WHERE id=?
                        """,
                        (_id,),
                    ).fetchone()
                    if db_row:
                        c.execute(
                            """
                            INSERT OR REPLACE INTO assign_archive
                            (id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, deleted_at, konsumen_nama, alamat_konsumen, alamat_project, konsumen_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (*db_row, datetime.now().isoformat()),
                        )
                        c.execute("DELETE FROM assign WHERE id=?", (_id,))
                        moved += 1
                conn.commit()
                st.success(f"{moved} penugasan dipindahkan ke arsip dan dihapus.")

            st.subheader("🗑️ Hapus Penugasan")
            delete_rows_with_dat_editor(df_assign, "assign", delete_assign_callback)
        else:
            st.info("Belum ada penugasan.")

        st.divider()
        df_archive = pd.read_sql(
            """
            SELECT id, nama_teknisi, tgl, alamat_konsumen, alamat_project, status, lat, long, jenis_project, deleted_at, konsumen_nama, konsumen_id
            FROM assign_archive
            ORDER BY deleted_at DESC
            """,
            conn,
        )

        if not df_archive.empty:
            st.subheader("Arsip Penugasan (Restore / Undo)")

            def restore_assign_callback(to_restore_df):
                restored = 0
                blocked = []
                for _, row in to_restore_df.iterrows():
                    _id = row["id"]
                    db_row = c.execute(
                        """
                        SELECT id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama, alamat_konsumen, alamat_project, konsumen_id
                        FROM assign_archive WHERE id=?
                        """,
                        (_id,),
                    ).fetchone()

                    if not db_row:
                        continue

                    try:
                        c.execute(
                            """
                            INSERT INTO assign
                            (id, nama_teknisi, tgl, alamat, status, lat, long, jenis_project, konsumen_nama, alamat_konsumen, alamat_project, konsumen_id)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            db_row,
                        )
                        c.execute("DELETE FROM assign_archive WHERE id=?", (_id,))
                        restored += 1
                    except sqlite3.IntegrityError:
                        blocked.append(_id)

                conn.commit()
                if restored:
                    st.success(f"{restored} arsip berhasil dikembalikan ke daftar penugasan.")
                if blocked:
                    st.error("Gagal restore beberapa item karena data sudah ada: " + ", ".join(blocked))

            restore_rows_with_dat_editor(df_archive, "archive", restore_assign_callback)
        else:
            st.info("Belum ada arsip penugasan.")


# =========================
# MENU 6
# =========================
elif menu == "Update Status":
    st.title("🔄 Update Status Pengerjaan Proyek")

    df_assign = pd.read_sql(
        """
        SELECT id, nama_teknisi, tgl, alamat_konsumen, alamat_project, status, lat, long, jenis_project, konsumen_nama
        FROM assign
        ORDER BY tgl DESC
        """,
        conn,
    )

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
                            <span class="subtle">{row['tgl']} · {str(row['alamat_project'])[:70]}</span><br>
                            <span style="background:{color};color:white;padding:4px 10px;border-radius:12px;font-size:12px;">
                            {emoji} {norm_stat.upper()}
                            </span>
                            """,
                            unsafe_allow_html=True,
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


# =========================
# FOOTER
# =========================
st.sidebar.markdown("---")
st.sidebar.caption("Developed by Muhammad Bey Trisnawan")