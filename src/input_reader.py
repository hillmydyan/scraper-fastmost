"""Excel and CSV Input Reader & Validator for FastMoss Scraper"""
from pathlib import Path
from typing import List, Tuple
import pandas as pd
from src.models import CreatorInput


class InputReader:
    @staticmethod
    def read_input(file_path: Path, default_country: str = "ID") -> Tuple[List[CreatorInput], dict]:
        """
        Membaca file input .xlsx atau .csv.
        Melakukan validasi:
        - Kolom 'nama_kreator' wajib ada
        - Membersihkan spasi ganda dan trim
        - Menghapus baris kosong
        - Deduplikasi case-insensitive
        - Batas maksimal 500 baris
        Return: (list_of_CreatorInput, stats_dict)
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File input '{file_path}' tidak ditemukan.")

        if path.suffix.lower() in [".xlsx", ".xls"]:
            df = pd.read_excel(path, sheet_name=0)
        elif path.suffix.lower() == ".csv":
            df = pd.read_csv(path)
        else:
            raise ValueError("Format file tidak didukung. Harap gunakan file .xlsx atau .csv.")

        df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]

        if "nama_kreator" not in df.columns:
            alt_candidates = ["kreator", "creator", "username", "nickname", "id_tiktok", "nama"]
            found_col = None
            for c in df.columns:
                if any(alt in c for alt in alt_candidates):
                    found_col = c
                    break
            if found_col:
                df = df.rename(columns={found_col: "nama_kreator"})
            else:
                raise ValueError("Kolom wajib 'nama_kreator' tidak ditemukan dalam file input.")

        total_rows_initial = len(df)
        empty_rows_count = 0
        duplicate_count = 0

        valid_creators: List[CreatorInput] = []
        seen_names = set()

        for _, row in df.iterrows():
            raw_name = str(row.get("nama_kreator", "")).strip()

            if not raw_name or raw_name.lower() == "nan":
                empty_rows_count += 1
                continue

            clean_name = " ".join(raw_name.split())
            key_name = clean_name.lower().replace("@", "")

            if key_name in seen_names:
                duplicate_count += 1
                continue

            seen_names.add(key_name)

            row_country = str(row.get("negara", "")).strip().upper()
            if not row_country or row_country == "NAN":
                row_country = default_country.upper()

            catatan = str(row.get("catatan", "")).strip()
            if catatan.lower() == "nan":
                catatan = ""

            valid_creators.append(CreatorInput(
                nama_kreator=clean_name,
                negara=row_country,
                catatan=catatan
            ))

        if len(valid_creators) > 500:
            valid_creators = valid_creators[:500]

        stats = {
            "total_initial": total_rows_initial,
            "valid_count": len(valid_creators),
            "duplicates_removed": duplicate_count,
            "empty_rows_removed": empty_rows_count
        }

        return valid_creators, stats

