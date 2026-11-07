"""Excel Generator and Formatter for FastMoss Scraper"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from src.models import VideoItem, CreatorSummary, CreatorLog, JobConfig
from src.utils import parse_revenue_value
from src.config import OUTPUTS_DIR


class ExcelHandler:
    def __init__(self):
        # Styles
        self.header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        self.header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        self.sub_header_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
        
        # Yellow highlight for AD badge
        self.ad_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
        self.ad_font = Font(name="Calibri", size=11, bold=True, color="B25900")
        
        # Borders
        thin_border = Side(style="thin", color="D9D9D9")
        self.cell_border = Border(left=thin_border, right=thin_border, top=thin_border, bottom=thin_border)
        
        # Fonts
        self.regular_font = Font(name="Calibri", size=10)
        self.link_font = Font(name="Calibri", size=10, color="0563C1", underline="single")
        self.bold_font = Font(name="Calibri", size=10, bold=True)

    def generate_report(
        self,
        videos_filtered: List[VideoItem],
        videos_other: List[VideoItem],
        summaries: List[CreatorSummary],
        logs: List[CreatorLog],
        config: JobConfig,
        custom_filepath: Optional[Path] = None
    ) -> Path:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        # 1. Sheet Video (Lolos filter)
        ws_video = wb.create_sheet(title="Video")
        self._write_video_sheet(ws_video, videos_filtered, is_filtered=True)

        # 2. Sheet Video Lainnya (Jika ada video yang tidak lolos filter)
        if videos_other:
            ws_other = wb.create_sheet(title="Video Lainnya")
            self._write_video_sheet(ws_other, videos_other, is_filtered=False)

        # 3. Sheet Ringkasan Kreator
        ws_summary = wb.create_sheet(title="Ringkasan Kreator")
        self._write_summary_sheet(ws_summary, summaries)

        # 4. Sheet Log
        ws_log = wb.create_sheet(title="Log")
        self._write_log_sheet(ws_log, logs)

        # File naming
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        country_code = config.country.upper()
        if custom_filepath:
            filepath = custom_filepath
        else:
            filepath = OUTPUTS_DIR / f"fastmoss_{country_code}_{timestamp}.xlsx"

        wb.save(filepath)
        return filepath

    def _write_video_sheet(self, ws, videos: List[VideoItem], is_filtered: bool):
        headers = [
            "Nama kreator (input)",
            "Nickname FastMoss",
            "ID TikTok",
            "URL detail FastMoss",
            "Negara",
            "Ads",
            "Durasi video (detik)",
            "Waktu rilis",
            "Tipe video",
            "Penjualan video (unit)",
            "Penjualan dari video (nilai)",
            "Jumlah putaran",
            "Tingkat interaksi (%)",
            "Nama produk",
            "Link produk / ID produk",
            "Kategori produk",
            "URL video",
            "Diambil pada"
        ]

        ws.append(headers)
        ws.freeze_panes = "A2"

        for col_num, _ in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = self.header_font
            cell.fill = self.header_fill if is_filtered else self.sub_header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.row_dimensions[1].height = 28

        sorted_videos = sorted(
            videos,
            key=lambda x: (
                x.nama_kreator_input,
                -parse_revenue_value(x.penjualan_video_nilai),
                -(x.penjualan_video_unit or 0)
            )
        )

        for row_idx, v in enumerate(sorted_videos, start=2):
            row_data = [
                v.nama_kreator_input,
                v.nickname_fastmoss,
                v.tiktok_id,
                v.url_detail_fastmoss or "",
                v.negara,
                v.ads or "",
                v.durasi_detik if v.durasi_detik is not None else "",
                v.waktu_rilis or "",
                v.tipe_video or "",
                v.penjualan_video_unit if v.penjualan_video_unit is not None else 0,
                v.penjualan_video_nilai or "",
                v.jumlah_putaran if v.jumlah_putaran is not None else 0,
                v.tingkat_interaksi if v.tingkat_interaksi is not None else 0.0,
                v.nama_produk or "",
                v.link_produk or "",
                v.kategori_produk or "",
                v.url_video or "",
                v.diambil_pada
            ]
            ws.append(row_data)
            ws.row_dimensions[row_idx].height = 20

            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = self.regular_font
                cell.border = self.cell_border
                cell.alignment = Alignment(vertical="center")

                if col_idx == 4 and v.url_detail_fastmoss:
                    cell.hyperlink = v.url_detail_fastmoss
                    cell.font = self.link_font

                elif col_idx == 6:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    if str(cell.value).strip().upper() == "AD":
                        cell.fill = self.ad_fill
                        cell.font = self.ad_font

                elif col_idx == 7 and isinstance(cell.value, (int, float)):
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")

                elif col_idx == 10 and isinstance(cell.value, (int, float)):
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")

                elif col_idx == 12 and isinstance(cell.value, (int, float)):
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")

                elif col_idx == 13 and isinstance(cell.value, (int, float)):
                    cell.number_format = "0.00%"
                    cell.alignment = Alignment(horizontal="right", vertical="center")

                elif col_idx == 15 and v.link_produk:
                    cell.hyperlink = v.link_produk
                    cell.font = self.link_font

                elif col_idx == 17 and v.url_video:
                    cell.hyperlink = v.url_video
                    cell.font = self.link_font

        self._autofit_columns(ws)

    def _write_summary_sheet(self, ws, summaries: List[CreatorSummary]):
        headers = [
            "Nama input",
            "Nickname FastMoss",
            "ID TikTok",
            "Status",
            "Jumlah Video (Periode)",
            "Jumlah Video AD",
            "Total Penjualan Video (Unit)",
            "Produk Terlaris",
            "URL Detail FastMoss",
            "Catatan"
        ]

        ws.append(headers)
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 28

        for col_num, _ in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = self.header_font
            cell.fill = self.header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        status_colors = {
            "selesai": "E2EFDA",
            "tanpa video": "FFF2CC",
            "tidak ditemukan": "FCE4D6",
            "ambigu": "EDEDED",
            "gagal": "F8CBAD"
        }

        for row_idx, s in enumerate(summaries, start=2):
            row_data = [
                s.nama_input,
                s.nickname,
                s.tiktok_id,
                s.status,
                s.jumlah_video_7hari,
                s.jumlah_video_ad,
                s.total_penjualan_video,
                s.produk_terlaris,
                s.url_detail,
                s.catatan
            ]
            ws.append(row_data)
            ws.row_dimensions[row_idx].height = 20

            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = self.regular_font
                cell.border = self.cell_border
                cell.alignment = Alignment(vertical="center")

                if col_idx == 4:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    color = status_colors.get(s.status.lower(), "FFFFFF")
                    cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                    cell.font = self.bold_font

                elif col_idx in [5, 6, 7]:
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")

                elif col_idx == 9 and s.url_detail:
                    cell.hyperlink = s.url_detail
                    cell.font = self.link_font

        self._autofit_columns(ws)

    def _write_log_sheet(self, ws, logs: List[CreatorLog]):
        headers = [
            "Nama input",
            "Status",
            "Pesan error / Detail",
            "Waktu mulai",
            "Waktu selesai",
            "Durasi (detik)"
        ]

        ws.append(headers)
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 28

        for col_num, _ in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = self.header_font
            cell.fill = self.header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for row_idx, log in enumerate(logs, start=2):
            row_data = [
                log.nama_input,
                log.status,
                log.pesan_error,
                log.waktu_mulai,
                log.waktu_selesai,
                round(log.durasi_detik, 1)
            ]
            ws.append(row_data)
            ws.row_dimensions[row_idx].height = 20

            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = self.regular_font
                cell.border = self.cell_border
                cell.alignment = Alignment(vertical="center")

                if col_idx == 2:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif col_idx == 6:
                    cell.number_format = "0.0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")

        self._autofit_columns(ws)

    def _autofit_columns(self, ws):
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or "")
                if len(val) > max_len:
                    max_len = min(len(val), 60)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

