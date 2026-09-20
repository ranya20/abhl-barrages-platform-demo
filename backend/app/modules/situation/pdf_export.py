from __future__ import annotations

import base64
import platform
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException


def _verify_pdf(pdf_path: Path) -> Path:
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise HTTPException(
            status_code=500,
            detail="La conversion PDF a échoué : le fichier PDF n'a pas été créé.",
        )

    data = pdf_path.read_bytes()
    if len(data) < 1000 or not data.startswith(b"%PDF"):
        raise HTTPException(
            status_code=500,
            detail=(
                "La conversion PDF a produit un fichier invalide. "
                "Vérifiez que Microsoft Excel ou LibreOffice est installé sur ce PC."
            ),
        )

    return pdf_path


def _find_soffice() -> str | None:
    direct = shutil.which("soffice") or shutil.which("libreoffice")
    if direct:
        return direct

    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]

    for candidate in candidates:
        if Path(candidate).exists():
            return candidate

    return None


def _convert_with_libreoffice(xlsx_path: Path, pdf_path: Path) -> Path:
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice introuvable.")

    tmp_dir = pdf_path.parent

    completed = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_dir),
            str(xlsx_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "LibreOffice n'a pas pu convertir le fichier. "
            + (completed.stderr or completed.stdout or "")
        )

    generated_pdf = tmp_dir / (xlsx_path.stem + ".pdf")
    if generated_pdf.exists() and generated_pdf != pdf_path:
        if pdf_path.exists():
            pdf_path.unlink()
        generated_pdf.rename(pdf_path)

    return _verify_pdf(pdf_path)


def _convert_with_excel_powershell(xlsx_path: Path, pdf_path: Path) -> Path:
    if platform.system().lower() != "windows":
        raise RuntimeError("Conversion Microsoft Excel disponible seulement sous Windows.")

    xlsx = str(xlsx_path.resolve())
    pdf = str(pdf_path.resolve())

    ps_script = f"""
$ErrorActionPreference = "Stop"

$xlsx = @'
{xlsx}
'@

$pdf = @'
{pdf}
'@

$excel = $null
$workbook = $null

try {{
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.ScreenUpdating = $false

    $workbook = $excel.Workbooks.Open($xlsx, 0, $true)

    # 0 = xlTypePDF
    # Quality 0 = standard
    # IncludeDocProperties = true
    # IgnorePrintAreas = false pour garder les pages/mises en page du fichier Excel
    $workbook.ExportAsFixedFormat(0, $pdf, 0, $true, $false)
}}
finally {{
    if ($workbook -ne $null) {{
        $workbook.Close($false)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) | Out-Null
    }}

    if ($excel -ne $null) {{
        $excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
    }}

    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}}
"""

    encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        text=True,
        timeout=150,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "Microsoft Excel n'a pas pu convertir le fichier en PDF. "
            + (completed.stderr or completed.stdout or "")
        )

    return _verify_pdf(pdf_path)


def convert_excel_to_pdf(xlsx_path: Path) -> Path:
    """
    Convertit un fichier Situation quotidienne .xlsx en PDF.

    Objectif : le PDF doit contenir les pages du fichier Excel avec la même
    mise en page. Sur Windows, la priorité est Microsoft Excel Desktop,
    car il respecte mieux les zones d'impression et la pagination Excel.
    Fallback : LibreOffice si disponible.
    """
    xlsx_path = Path(xlsx_path)

    if not xlsx_path.exists():
        raise HTTPException(status_code=500, detail=f"Fichier Excel introuvable : {xlsx_path}")

    pdf_path = xlsx_path.with_name(f"{xlsx_path.stem} - {uuid4().hex[:8]}.pdf")

    errors: list[str] = []

    try:
        return _convert_with_excel_powershell(xlsx_path, pdf_path)
    except Exception as exc:
        errors.append(f"Excel/PowerShell : {exc}")

    try:
        return _convert_with_libreoffice(xlsx_path, pdf_path)
    except Exception as exc:
        errors.append(f"LibreOffice : {exc}")

    raise HTTPException(
        status_code=500,
        detail=(
            "Impossible de générer le PDF automatiquement. "
            "Installez Microsoft Excel Desktop ou LibreOffice sur ce PC. "
            "Détails : " + " | ".join(errors)
        ),
    )

# === ABHL V28 SELECTIVE SITUATION PDF START ===
#
# PDF complet OU PDF d'une seule feuille Excel.
# Sur Windows, Microsoft Excel exporte directement la feuille choisie.
# Pour le fallback LibreOffice, une copie OOXML temporaire masque toutes les
# autres feuilles sans réécrire les cellules/formules/mises en page.

import tempfile as _abhl_v28_tempfile
import zipfile as _abhl_v28_zipfile
import xml.etree.ElementTree as _abhl_v28_ET


if "_abhl_v28_original_convert_excel_to_pdf" not in globals():
    _abhl_v28_original_convert_excel_to_pdf = convert_excel_to_pdf


def _abhl_v28_convert_with_excel_selected(
    xlsx_path: Path,
    pdf_path: Path,
    sheet_name: str,
) -> Path:
    if platform.system().lower() != "windows":
        raise RuntimeError("Conversion Microsoft Excel disponible seulement sous Windows.")

    xlsx = str(Path(xlsx_path).resolve())
    pdf = str(Path(pdf_path).resolve())
    sheet = str(sheet_name)

    ps_script = f"""
$ErrorActionPreference = "Stop"

$xlsx = @'
{xlsx}
'@

$pdf = @'
{pdf}
'@

$sheetName = @'
{sheet}
'@

$excel = $null
$workbook = $null
$worksheet = $null

try {{
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.ScreenUpdating = $false

    $workbook = $excel.Workbooks.Open($xlsx, 0, $true)
    $worksheet = $workbook.Worksheets.Item($sheetName)

    # 0 = xlTypePDF, qualité standard, zones d'impression respectées.
    # ExportAsFixedFormat sur la Worksheet garantit qu'aucune autre feuille
    # du classeur ne se retrouve dans le PDF demandé.
    $worksheet.ExportAsFixedFormat(0, $pdf, 0, $true, $false)
}}
finally {{
    if ($worksheet -ne $null) {{
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($worksheet) | Out-Null
    }}

    if ($workbook -ne $null) {{
        $workbook.Close($false)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) | Out-Null
    }}

    if ($excel -ne $null) {{
        $excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
    }}

    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}}
"""

    encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        text=True,
        timeout=150,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Microsoft Excel n'a pas pu exporter la feuille demandée. "
            + (completed.stderr or completed.stdout or "")
        )
    return _verify_pdf(pdf_path)


def _abhl_v28_single_visible_sheet_copy(
    xlsx_path: Path,
    sheet_name: str,
    output_path: Path,
) -> Path:
    """
    Copie OOXML conservant intégralement les feuilles, styles, images, formules
    et zones d'impression. Seul xl/workbook.xml est modifié pour masquer les
    feuilles autres que celle demandée.
    """
    xlsx_path = Path(xlsx_path)
    output_path = Path(output_path)

    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_tag = f"{{{ns_main}}}sheet"
    workbook_view_tag = f"{{{ns_main}}}workbookView"

    with _abhl_v28_zipfile.ZipFile(xlsx_path, "r") as zin:
        workbook_xml = zin.read("xl/workbook.xml")
        root = _abhl_v28_ET.fromstring(workbook_xml)
        sheets = list(root.iter(sheet_tag))

        selected_index = None
        for index, node in enumerate(sheets):
            name = node.attrib.get("name")
            if name == sheet_name:
                selected_index = index
                node.attrib.pop("state", None)
            else:
                node.set("state", "hidden")

        if selected_index is None:
            raise RuntimeError(f"Feuille Excel introuvable : {sheet_name}")

        # Active la feuille demandée pour les moteurs qui utilisent activeTab.
        for view in root.iter(workbook_view_tag):
            view.set("activeTab", str(selected_index))
            view.set("firstSheet", str(selected_index))

        new_workbook_xml = _abhl_v28_ET.tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
        )

        with _abhl_v28_zipfile.ZipFile(
            output_path,
            "w",
            compression=_abhl_v28_zipfile.ZIP_DEFLATED,
        ) as zout:
            for info in zin.infolist():
                if info.filename == "xl/workbook.xml":
                    zout.writestr(info, new_workbook_xml)
                else:
                    zout.writestr(info, zin.read(info.filename))

    return output_path


def _abhl_v28_convert_with_libreoffice_selected(
    xlsx_path: Path,
    pdf_path: Path,
    sheet_name: str,
) -> Path:
    temp_xlsx = pdf_path.with_name(
        f"{pdf_path.stem}-selected-{uuid4().hex[:8]}.xlsx"
    )
    try:
        _abhl_v28_single_visible_sheet_copy(xlsx_path, sheet_name, temp_xlsx)
        return _convert_with_libreoffice(temp_xlsx, pdf_path)
    finally:
        try:
            if temp_xlsx.exists():
                temp_xlsx.unlink()
        except Exception:
            pass


def convert_excel_to_pdf(
    xlsx_path: Path,
    sheet_name: str | None = None,
) -> Path:
    """
    Convertit la Situation en PDF.

    - sheet_name=None : PDF complet des feuilles exportées.
    - sheet_name="..." : uniquement la feuille demandée, avec sa zone
      d'impression et sa pagination Excel.

    La liste des feuilles autorisées est contrôlée dans la route FastAPI.
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Fichier Excel introuvable : {xlsx_path}",
        )

    suffix = ""
    if sheet_name:
        safe = "".join(
            ch if ch.isalnum() or ch in " _-()" else "_"
            for ch in str(sheet_name)
        ).strip()
        suffix = f" - {safe}" if safe else " - feuille"

    pdf_path = xlsx_path.with_name(
        f"{xlsx_path.stem}{suffix} - {uuid4().hex[:8]}.pdf"
    )

    if not sheet_name:
        return _abhl_v28_original_convert_excel_to_pdf(xlsx_path)

    errors: list[str] = []

    try:
        return _abhl_v28_convert_with_excel_selected(
            xlsx_path,
            pdf_path,
            sheet_name,
        )
    except Exception as exc:
        errors.append(f"Excel/PowerShell : {exc}")

    try:
        return _abhl_v28_convert_with_libreoffice_selected(
            xlsx_path,
            pdf_path,
            sheet_name,
        )
    except Exception as exc:
        errors.append(f"LibreOffice : {exc}")

    raise HTTPException(
        status_code=500,
        detail=(
            f"Impossible de générer le PDF de la feuille '{sheet_name}'. "
            "Microsoft Excel Desktop ou LibreOffice doit être disponible. "
            "Détails : " + " | ".join(errors)
        ),
    )

# === ABHL V28 SELECTIVE SITUATION PDF END ===
