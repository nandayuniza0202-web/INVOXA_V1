import re
from typing import Any

import pandas as pd

from database.supabase_client import supabase


CATEGORY_RULES: dict[str, list[str]] = {
    "ATK": [
        # Kertas
        "kertas hvs",
        "kertas a4",
        "kertas f4",
        "kertas folio",
        "kertas buffalo",
        "kertas karton",
        "kertas foto",
        "kertas glossy",
        "kertas label",
        "kertas karbon",
        "kertas kalkir",
        "kertas berwarna",
        "kertas manila",
        "kertas origami",
        "kertas continuous form",
        "sticky note",
        "post it",
        "memo tempel",
        "kertas",

        # Alat tulis
        "pulpen",
        "ballpoint",
        "ballpoint pen",
        "pena",
        "pensil",
        "pensil warna",
        "pensil mekanik",
        "isi pensil mekanik",
        "spidol permanen",
        "spidol whiteboard",
        "spidol papan tulis",
        "spidol",
        "marker",
        "stabilo",
        "highlighter",
        "penghapus",
        "penggaris",
        "tipex",
        "tip ex",
        "correction pen",
        "correction tape",
        "rautan",
        "jangka",
        "busur",
        "kapur tulis",

        # Pengarsipan
        "map snelhecter",
        "map snelhecther",
        "map plastik",
        "map kertas",
        "map folder",
        "map batik",
        "map gantung",
        "map folio",
        "map",
        "ordner",
        "binder",
        "amplop coklat",
        "amplop putih",
        "amplop panjang",
        "amplop",
        "folder",
        "file box",
        "box file",
        "clear holder",
        "clear book",
        "document keeper",
        "plastik laminating",
        "cover jilid",
        "spiral jilid",
        "paper fastener",
        "snelhecter",

        # Peralatan meja kantor
        "stapler",
        "staples",
        "isi staples",
        "isi stapler",
        "pelubang kertas",
        "perforator",
        "paper clip",
        "binder clip",
        "klip kertas",
        "penjepit kertas",
        "gunting",
        "cutter",
        "pisau cutter",
        "isi cutter",
        "lem kertas",
        "lem stik",
        "lem cair",
        "lem",
        "double tape",
        "doubletip",
        "double tip",
        "lakban dua sisi",
        "selotip dua sisi",
        "selotip",
        "isolasi bening",
        "lakban bening",
        "dispenser tape",
        "tempat pensil",
        "desk organizer",
        "bantalan stempel",
        "bak stempel",
        "stempel",
        "tinta stempel",
        "kalkulator",

        # Buku dan pencatatan
        "buku agenda",
        "buku tulis",
        "buku kas",
        "buku ekspedisi",
        "buku folio",
        "buku kwitansi",
        "buku kuitansi",
        "buku nota",
        "buku tamu",
        "buku register",
        "buku besar",
        "buku",
        "nota",
        "kwitansi",
        "kuitansi",
        "formulir",
        "form",
        "blanko",

        # Perlengkapan cetak
        "tinta printer",
        "tinta epson",
        "tinta canon",
        "tinta brother",
        "tinta hp",
        "cartridge",
        "toner",
        "drum printer",
        "pita printer",
        "ribbon printer",
        "refill tinta",
    ],

    "APD": [
        "alat pelindung diri",
        "masker medis",
        "masker bedah",
        "masker surgical",
        "masker kn95",
        "masker n95",
        "masker kain",
        "masker",
        "sarung tangan nitrile",
        "sarung tangan latex",
        "sarung tangan medis",
        "sarung tangan safety",
        "sarung tangan kerja",
        "sarung tangan",
        "kaos tangan",
        "handscoon",
        "hand glove",
        "nitrile",
        "latex",
        "helm safety",
        "helm proyek",
        "safety helmet",
        "rompi safety",
        "rompi proyek",
        "safety vest",
        "sepatu safety",
        "safety shoes",
        "sepatu boot",
        "safety boot",
        "penutup kepala",
        "hairnet",
        "face shield",
        "pelindung wajah",
        "kacamata safety",
        "kacamata pelindung",
        "safety glasses",
        "goggles",
        "earplug",
        "earmuff",
        "pelindung telinga",
        "apron",
        "celemek pelindung",
        "coverall",
        "wearpack",
        "jas laboratorium",
        "jas lab",
        "jas hujan",
        "pelindung lutut",
        "safety harness",
        "body harness",
        "respirator",
        "pelindung pernapasan",
    ],

    "Alat Kebersihan": [
        # Cairan dan bahan pembersih
        "sunlight",
        "mama lemon",
        "sabun cuci piring",
        "sabun cuci tangan",
        "sabun lantai",
        "sabun tangan",
        "hand soap",
        "sabun cair",
        "sabun batang",
        "sabun",
        "detergen cair",
        "detergen bubuk",
        "deterjen cair",
        "deterjen bubuk",
        "detergen",
        "deterjen",
        "pembersih lantai",
        "pembersih kaca",
        "pembersih toilet",
        "pembersih kamar mandi",
        "pembersih serbaguna",
        "pembersih",
        "wipol",
        "bayclin",
        "karbol",
        "disinfektan",
        "sanitizer",
        "hand sanitizer",
        "pewangi ruangan",
        "pewangi pakaian",
        "pewangi",
        "kapur barus",
        "kamper",
        "pemutih pakaian",
        "pemutih",
        "soda api",
        "pembersih saluran",
        "pembersih kerak",
        "pengharum toilet",
        "pengharum ruangan",

        # Peralatan kebersihan
        "sapu lidi",
        "sapu ijuk",
        "sapu lantai",
        "sapu",
        "kain pel",
        "pel lantai",
        "tongkat pel",
        "mop",
        "pel",
        "sikat lantai",
        "sikat toilet",
        "sikat kamar mandi",
        "sikat pakaian",
        "sikat",
        "kemoceng",
        "pengki",
        "serokan sampah",
        "tong sampah",
        "tempat sampah",
        "kantong sampah",
        "plastik sampah",
        "trash bag",
        "kain lap",
        "lap microfiber",
        "lap kaca",
        "lap",
        "kanebo",
        "spons cuci",
        "spons",
        "sponge",
        "sarung tangan karet",
        "wiper kaca",
        "pembersih jendela",
        "vacuum cleaner",
        "penyedot debu",
        "keset",
        "keset kaki",
        "sprayer",
        "botol semprot",

        # Tisu
        "tisu wajah",
        "tisu toilet",
        "tisu gulung",
        "tisu makan",
        "tisu basah",
        "tisu kering",
        "tisu jumbo",
        "tissue wajah",
        "tissue toilet",
        "tissue roll",
        "tissu",
        "tissue",
        "tisu",
    ],

    "Alat Kelengkapan": [
        # Kemasan makanan dan minuman
        "kotak bento",
        "bento box",
        "bento",
        "kotak makan",
        "food container",
        "meal box",
        "lunch box",
        "paper bowl",
        "paper cup",
        "cup plastik",
        "gelas plastik",
        "gelas kertas",
        "sendok plastik",
        "garpu plastik",
        "pisau plastik",
        "sedotan",
        "straw",
        "tusuk gigi",
        "tusuk sate",
        "aluminium foil",
        "plastic wrap",
        "cling wrap",
        "wrapping",
        "plastik wrapping",
        "kantong plastik",
        "plastik bening",
        "plastik klip",
        "plastik ziplock",
        "plastik packing",
        "plastik makanan",
        "plastik kresek",
        "plastik",

        # Wadah dan perlengkapan umum
        "galon",
        "dispenser air",
        "dispenser",
        "ember",
        "gayung",
        "baskom",
        "nampan",
        "tray",
        "wadah",
        "container",
        "keranjang",
        "rak piring",
        "rak susun",
        "rak",
        "botol minum",
        "botol",
        "toples",
        "cool box",
        "kotak penyimpanan",
        "storage box",
        "termos",
        "teko",
        "cerek",
        "jerigen",

        # Tali dan pengikat
        "tali rafia",
        "tali nilon",
        "tali tambang",
        "tali",
        "karet gelang",
        "cable tie",
        "zip tie",

        # Kelengkapan gedung dan umum
        "baterai",
        "battery",
        "balon philips",
        "lampu philips",
        "bohlam philips",
        "balon lampu",
        "balon",
        "gembok",
        "kunci gembok",
        "terpal",
        "selang air",
        "selang",
        "jam dinding",
        "lampu led",
        "lampu",
        "kabel listrik",
        "kabel roll",
        "kabel",
        "terminal listrik",
        "stop kontak",
        "colokan listrik",
        "steker",
        "saklar",
        "bohlam",
        "kipas angin",
        "payung",
        "kursi plastik",
        "meja plastik",
        "papan nama",
        "papan informasi",
        "papan tulis",
        "whiteboard",
        "paku",
        "sekrup",
        "obeng",
        "tang",
        "palu",
        "meteran",
        "lakban hitam",
        "lakban coklat",
        "lakban",
    ],
}


def normalize_text(text: Any) -> str:
    """
    Membersihkan teks agar lebih mudah dicocokkan.

    Contoh:
    "Kertas HVS A4, 80 GSM" menjadi "kertas hvs a4 80 gsm".
    """

    if text is None:
        return ""

    try:
        if pd.isna(text):
            return ""
    except (TypeError, ValueError):
        pass

    normalized = str(text).lower().strip()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()


def is_empty_value(value: Any) -> bool:
    """Memeriksa apakah nilai kosong, None, NaN, atau hanya spasi."""

    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass

    return not str(value).strip()


def get_first_nonempty_value(
    row: pd.Series,
    column_names: list[str],
) -> str:
    """Mengambil nilai pertama yang tidak kosong dari beberapa kolom."""

    for column_name in column_names:
        value = row.get(column_name)

        if not is_empty_value(value):
            return str(value).strip()

    return ""


def get_categories() -> list[dict[str, Any]]:
    """
    Mengambil seluruh kategori terbaru langsung dari Supabase.

    Cache tidak digunakan agar kategori baru seperti ATK
    langsung terbaca oleh aplikasi.
    """

    response = (
        supabase.table("categories")
        .select("id, name, description")
        .order("name")
        .execute()
    )

    return response.data or []


def get_category_by_name(
    category_name: str,
) -> dict[str, Any] | None:
    """
    Mengambil kategori berdasarkan nama.

    Pencarian tidak membedakan huruf besar dan kecil.
    """

    normalized_target = normalize_text(category_name)

    if not normalized_target:
        return None

    categories = get_categories()

    for category in categories:
        database_category_name = normalize_text(
            category.get("name", "")
        )

        if database_category_name == normalized_target:
            return category

    return None


def get_uncategorized_category() -> dict[str, Any] | None:
    """Mengambil kategori cadangan Belum Dikategorikan."""

    return get_category_by_name("Belum Dikategorikan")


def calculate_keyword_score(
    description: str,
    keyword: str,
) -> int:
    """
    Menghitung skor kecocokan kata kunci.

    Frasa yang lebih panjang dan spesifik mendapat skor lebih tinggi.
    """

    normalized_description = normalize_text(description)
    normalized_keyword = normalize_text(keyword)

    if not normalized_description or not normalized_keyword:
        return 0

    pattern = rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)"

    if not re.search(pattern, normalized_description):
        return 0

    word_count = len(normalized_keyword.split())
    character_count = len(normalized_keyword)

    return (word_count * 100) + character_count


def predict_category(
    description: str,
) -> dict[str, Any] | None:
    """
    Menentukan kategori berdasarkan nama atau uraian barang.

    Hasil berisi:
    - category_id
    - category_name
    - confidence
    - source
    - matched_keyword
    """

    normalized_description = normalize_text(description)

    best_category_name = "Belum Dikategorikan"
    best_keyword: str | None = None
    best_score = 0

    if normalized_description:
        for category_name, keywords in CATEGORY_RULES.items():
            category_best_score = 0
            category_best_keyword: str | None = None

            for keyword in keywords:
                keyword_score = calculate_keyword_score(
                    normalized_description,
                    keyword,
                )

                if keyword_score > category_best_score:
                    category_best_score = keyword_score
                    category_best_keyword = keyword

            if category_best_score > best_score:
                best_score = category_best_score
                best_category_name = category_name
                best_keyword = category_best_keyword

    category = get_category_by_name(best_category_name)

    if not category:
        category = get_uncategorized_category()

    if not category:
        return None

    if best_score > 0:
        matched_word_count = len(
            normalize_text(best_keyword).split()
        )

        if matched_word_count >= 3:
            confidence = 0.98
        elif matched_word_count == 2:
            confidence = 0.94
        else:
            confidence = 0.88

        source = "keyword"
    else:
        confidence = 0.0
        source = "automatic"

    return {
        "category_id": category["id"],
        "category_name": category["name"],
        "confidence": confidence,
        "source": source,
        "matched_keyword": best_keyword,
    }


def apply_predicted_categories(
    dataframe: pd.DataFrame,
    overwrite_existing: bool = False,
) -> pd.DataFrame:
    """
    Mengisi kategori barang pada DataFrame.

    Prioritas sumber uraian:
    1. raw_description
    2. description
    3. product_name
    4. name
    5. item_name

    Gunakan overwrite_existing=True saat pertama kali file diimpor.
    Gunakan overwrite_existing=False sebelum data disimpan.
    """

    if dataframe is None:
        return pd.DataFrame()

    dataframe = dataframe.copy()

    required_columns: dict[str, Any] = {
        "category": "",
        "category_id": "",
        "category_confidence": 0.0,
        "category_source": "",
        "category_matched_keyword": "",
    }

    for column_name, default_value in required_columns.items():
        if column_name not in dataframe.columns:
            dataframe[column_name] = default_value

    description_columns = [
        "raw_description",
        "description",
        "product_name",
        "name",
        "item_name",
    ]

    for index, row in dataframe.iterrows():
        current_category = row.get("category")

        if (
            not overwrite_existing
            and not is_empty_value(current_category)
        ):
            continue

        description = get_first_nonempty_value(
            row,
            description_columns,
        )

        prediction = predict_category(description)

        if not prediction:
            continue

        dataframe.at[index, "category"] = (
            prediction["category_name"]
        )
        dataframe.at[index, "category_id"] = (
            prediction["category_id"]
        )
        dataframe.at[index, "category_confidence"] = (
            prediction["confidence"]
        )
        dataframe.at[index, "category_source"] = (
            prediction["source"]
        )
        dataframe.at[
            index,
            "category_matched_keyword",
        ] = prediction["matched_keyword"] or ""

    return dataframe


def predict_single_item(description: str) -> str:
    """
    Mengembalikan nama kategori untuk satu barang.

    Digunakan untuk input manual.
    """

    prediction = predict_category(description)

    if not prediction:
        return "Belum Dikategorikan"

    return str(prediction["category_name"])