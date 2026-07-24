import os

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()


def get_setting(name: str) -> str | None:
    """
    Membaca konfigurasi dari environment variable lokal
    atau Streamlit Secrets saat aplikasi berjalan di cloud.
    """

    value = os.getenv(name)

    if value:
        return value

    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass

    return None


def get_supabase_client() -> Client:
    """Membuat koneksi Supabase untuk lokal dan Streamlit Cloud."""

    supabase_url = get_setting("SUPABASE_URL")
    supabase_key = get_setting("SUPABASE_KEY")

    if not supabase_url:
        raise ValueError(
            "SUPABASE_URL belum tersedia di file .env "
            "atau Streamlit Secrets."
        )

    if not supabase_key:
        raise ValueError(
            "SUPABASE_KEY belum tersedia di file .env "
            "atau Streamlit Secrets."
        )

    return create_client(
        supabase_url,
        supabase_key,
    )


supabase = get_supabase_client()