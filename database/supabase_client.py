import os

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()


def get_supabase_client() -> Client:
    """Membuat koneksi ke Supabase."""

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url:
        raise ValueError("SUPABASE_URL belum diisi di file .env")

    if not supabase_key:
        raise ValueError("SUPABASE_KEY belum diisi di file .env")

    return create_client(supabase_url, supabase_key)


supabase = get_supabase_client()