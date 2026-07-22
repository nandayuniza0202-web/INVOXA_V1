import streamlit as st

st.set_page_config(
    page_title="INVOXA",
    page_icon="🧾",
    layout="wide",
)

if "invoice_items" not in st.session_state:
    st.session_state.invoice_items = []

if "customer_name" not in st.session_state:
    st.session_state.customer_name = ""

if "customer_address" not in st.session_state:
    st.session_state.customer_address = ""

if "invoice_period" not in st.session_state:
    st.session_state.invoice_period = ""

st.markdown(
    """
    # 👋 Halo, Papi S!

    ## Saya adalah **INVOXA**
    **Asisten Budget Matcher** yang dirancang untuk membantu proses penyusunan invoice, mulai dari input nota, matching kategori, penyesuaian pagu, hingga pembuatan invoice akhir.

    Silakan pilih menu di sebelah kiri untuk memulai.

    ---

    ### Fitur Utama

    **📄 Input Nota**  
    Masukkan data melalui Excel, OCR, atau input manual.

    **🧠 Matching**  
    Periksa dan kelompokkan barang sesuai kategori.

    **📊 Revision**  
    Sesuaikan harga dan kuantitas agar mendekati total pagu target.

    **📥 Download**  
    Hasilkan invoice Word sesuai template yang telah dipilih.

    ---

    <div style="
        text-align: center;
        color: #9CA3AF;
        font-size: 13px;
        margin-top: 45px;
        line-height: 1.8;
    ">
        <strong>INVOXA v1.0</strong><br>
        Khusus dibuat untuk <strong>Papi S.</strong><br>
        © 2026 NYE. All Rights Reserved.
    </div>
    """,
    unsafe_allow_html=True,
)