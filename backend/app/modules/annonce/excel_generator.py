from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
import copy
import posixpath
import re
import xml.etree.ElementTree as ET

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, settings
from app.modules.annonce.mappings import (
    CRUES_BARRAGE_ROWS,
    DATA_ROW_COUNT,
    MONTH_NAMES_FR_UPPER,
    SHEET_CONFIGS,
    TARGET_BARRAGE_CODES,
)
from app.modules.annonce.repository import load_annonce_data, register_export


TEMPLATE_NAME = "annonce_TEMPLATE.xlsx"

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
X14AC_NS = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"
X15_NS = "http://schemas.microsoft.com/office/spreadsheetml/2010/11/main"
EXT_PROPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"

# IMPORTANT : Excel exige que les préfixes cités dans mc:Ignorable
# restent déclarés avec leurs noms d’origine. ElementTree les renomme
# sinon en ns1/ns2, ce qui déclenche la réparation du classeur par Excel.
ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)
ET.register_namespace("mc", MC_NS)
ET.register_namespace("x14ac", X14AC_NS)
ET.register_namespace("x15", X15_NS)
ET.register_namespace("vt", VT_NS)


def qn(tag: str) -> str:
    return f"{{{MAIN_NS}}}{tag}"


def serialize_ooxml(root: ET.Element, original_data: bytes) -> bytes:
    """
    Sérialise un XML OOXML sans perdre les déclarations de namespaces
    référencées par ``mc:Ignorable``.

    Excel considère comme invalide un document contenant, par exemple,
    ``mc:Ignorable="x14ac"`` sans ``xmlns:x14ac=...``.
    ``xml.etree.ElementTree`` supprime parfois une déclaration inutilisée ou
    renomme les préfixes en ``ns1``/``ns2``. Cette fonction réinjecte les
    déclarations originales indispensables après la sérialisation.
    """
    data = ET.tostring(root, encoding="utf-8", xml_declaration=False)

    original_text = original_data.decode("utf-8", errors="replace")
    original_root_match = re.search(r"<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?(?:workbook|worksheet)\b[^>]*>", original_text)
    if original_root_match is None:
        return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + data

    original_root_tag = original_root_match.group(0)
    declarations = dict(
        re.findall(r'xmlns:([A-Za-z_][A-Za-z0-9_.-]*)="([^"]+)"', original_root_tag)
    )

    ignorable_match = re.search(r'mc:Ignorable="([^"]+)"', original_root_tag)
    required_prefixes = {"mc"}
    if ignorable_match:
        required_prefixes.update(ignorable_match.group(1).split())

    serialized_root_match = re.search(rb"<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?(?:workbook|worksheet)\b[^>]*>", data)
    if serialized_root_match is not None:
        serialized_root_tag = serialized_root_match.group(0)
        additions: list[bytes] = []

        for prefix in sorted(required_prefixes):
            uri = declarations.get(prefix)
            if not uri:
                continue
            marker = f"xmlns:{prefix}=".encode("utf-8")
            if marker not in serialized_root_tag:
                additions.append(f' xmlns:{prefix}="{uri}"'.encode("utf-8"))

        if additions:
            replacement = serialized_root_tag[:-1] + b"".join(additions) + b">"
            data = (
                data[: serialized_root_match.start()]
                + replacement
                + data[serialized_root_match.end() :]
            )

    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + data


def resolve_template_path() -> Path:
    candidates = [
        BACKEND_DIR / "app" / "templates" / TEMPLATE_NAME,
        BACKEND_DIR / "templates" / TEMPLATE_NAME,
        BACKEND_DIR / "excel_templates" / TEMPLATE_NAME,
    ]

    try:
        candidates.append((BACKEND_DIR / settings.EXCEL_TEMPLATES_DIR / TEMPLATE_NAME).resolve())
    except Exception:
        pass

    for path in candidates:
        if path.exists():
            return path

    raise HTTPException(
        status_code=500,
        detail=(
            "Template annonce.xlsx introuvable. Place le modèle ici : "
            f"{BACKEND_DIR / 'app' / 'templates' / TEMPLATE_NAME}"
        ),
    )


def resolve_exports_dir() -> Path:
    try:
        path = Path(settings.DATA_EXPORTS_DIR)
    except Exception:
        path = BACKEND_DIR / "exports"

    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()

    path.mkdir(parents=True, exist_ok=True)
    return path


def value_or_none(value):
    return None if value is None else float(value)


def month_dates(month_start: date) -> list[date]:
    return [month_start + timedelta(days=offset) for offset in range(DATA_ROW_COUNT)]


def excel_serial(day: date, date_1904: bool = False) -> int:
    base = date(1904, 1, 1) if date_1904 else date(1899, 12, 30)
    return (day - base).days


def column_number(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        raise ValueError(f"Référence cellule invalide : {cell_ref}")

    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - 64
    return result


def _resolve_relationship_target(source_part: str, target: str) -> str:
    source_dir = posixpath.dirname(source_part)
    return posixpath.normpath(posixpath.join(source_dir, target)).lstrip("/")


def validate_xlsx_package(output_path: Path):
    """Bloque l'envoi si une relation OOXML interne est cassée."""
    required_parts = {
        "[Content_Types].xml",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
    }

    with ZipFile(output_path, "r") as archive:
        names = set(archive.namelist())
        missing_core = sorted(required_parts - names)
        if missing_core:
            raise RuntimeError(
                "Parties XLSX manquantes : " + ", ".join(missing_core)
            )

        damaged_entry = archive.testzip()
        if damaged_entry:
            raise RuntimeError(f"Entrée ZIP endommagée : {damaged_entry}")

        # Microsoft Excel refuse les XML qui déclarent mc:Ignorable
        # sans déclarer les préfixes cités (ex. x15).
        for xml_path in sorted(
            name for name in names if name.endswith((".xml", ".rels"))
        ):
            xml_text = archive.read(xml_path).decode("utf-8", errors="replace")
            root_match = re.search(r"<[^!?][^>]*>", xml_text)
            if root_match is None:
                continue
            root_tag = root_match.group(0)
            ignorable_match = re.search(r'mc:Ignorable="([^"]+)"', root_tag)
            if ignorable_match is None:
                continue
            declared_prefixes = set(
                re.findall(
                    r'xmlns:([A-Za-z_][A-Za-z0-9_.-]*)="[^"]+"',
                    root_tag,
                )
            )
            missing_prefixes = [
                prefix
                for prefix in ignorable_match.group(1).split()
                if prefix not in declared_prefixes
            ]
            if missing_prefixes:
                raise RuntimeError(
                    f"Namespaces OOXML manquants dans {xml_path}: "
                    + ", ".join(missing_prefixes)
                )

        for worksheet_path in sorted(
            name
            for name in names
            if name.startswith("xl/worksheets/")
            and name.endswith(".xml")
            and "/_rels/" not in name
        ):
            root = ET.fromstring(archive.read(worksheet_path))
            referenced_ids = {
                value
                for element in root.iter()
                for key, value in element.attrib.items()
                if key == f"{{{REL_NS}}}id"
            }
            if not referenced_ids:
                continue

            worksheet_name = posixpath.basename(worksheet_path)
            rels_path = posixpath.join(
                posixpath.dirname(worksheet_path),
                "_rels",
                f"{worksheet_name}.rels",
            )
            if rels_path not in names:
                raise RuntimeError(
                    f"Relations absentes pour {worksheet_path}: "
                    + ", ".join(sorted(referenced_ids))
                )

            rels_root = ET.fromstring(archive.read(rels_path))
            relationships = {
                item.attrib.get("Id"): item
                for item in rels_root.findall(
                    f"{{{PACKAGE_REL_NS}}}Relationship"
                )
            }
            for relationship_id in referenced_ids:
                relationship = relationships.get(relationship_id)
                if relationship is None:
                    raise RuntimeError(
                        f"Relation {relationship_id} absente pour {worksheet_path}"
                    )
                if relationship.attrib.get("TargetMode") == "External":
                    continue
                target = relationship.attrib.get("Target")
                if not target:
                    raise RuntimeError(
                        f"Cible vide pour {worksheet_path}/{relationship_id}"
                    )
                resolved_target = _resolve_relationship_target(
                    worksheet_path, target
                )
                if resolved_target not in names:
                    raise RuntimeError(
                        f"Cible OOXML absente : {resolved_target}"
                    )


class XlsxTemplateEditor:
    """
    Modifie uniquement les XML des cellules nécessaires dans le fichier xlsx.

    Contrairement à une réécriture complète avec une bibliothèque tableur,
    cette méthode conserve exactement les dessins, images, formes, liens,
    paramètres d'impression, styles et autres parties OOXML du modèle original.
    """

    def __init__(self, template_path: Path):
        self.template_path = template_path
        self.original_entries: dict[str, tuple[object, bytes]] = {}
        self.modified_entries: dict[str, bytes] = {}
        self.new_entries: dict[str, bytes] = {}
        self.sheet_paths: dict[str, str] = {}
        self.sheet_roots: dict[str, ET.Element] = {}
        self.date_1904 = False
        self._load_package()

    def _load_package(self):
        with ZipFile(self.template_path, "r") as archive:
            for info in archive.infolist():
                self.original_entries[info.filename] = (copy.copy(info), archive.read(info.filename))

        workbook_root = ET.fromstring(self.original_entries["xl/workbook.xml"][1])
        workbook_pr = workbook_root.find(qn("workbookPr"))
        self.date_1904 = bool(
            workbook_pr is not None
            and workbook_pr.attrib.get("date1904") in {"1", "true", "True"}
        )

        rels_root = ET.fromstring(self.original_entries["xl/_rels/workbook.xml.rels"][1])
        relationship_targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in rels_root.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
        }

        sheets = workbook_root.find(qn("sheets"))
        if sheets is None:
            raise RuntimeError("Le modèle annonce ne contient aucune feuille.")

        for sheet in sheets.findall(qn("sheet")):
            relationship_id = sheet.attrib[f"{{{REL_NS}}}id"]
            target = relationship_targets[relationship_id].lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            self.sheet_paths[sheet.attrib["name"]] = target

    def require_sheet(self, sheet_name: str) -> ET.Element:
        if sheet_name not in self.sheet_paths:
            raise HTTPException(
                status_code=500,
                detail=f"Feuille manquante dans le template annonce : {sheet_name}",
            )

        if sheet_name not in self.sheet_roots:
            path = self.sheet_paths[sheet_name]
            if path in self.original_entries:
                data = self.original_entries[path][1]
            elif path in self.new_entries:
                data = self.new_entries[path]
            else:
                raise RuntimeError(f"XML de feuille introuvable : {path}")
            self.sheet_roots[sheet_name] = ET.fromstring(data)

        return self.sheet_roots[sheet_name]

    @staticmethod
    def _strip_clone_relationship_references(root: ET.Element):
        """
        Retire uniquement les références externes propres à la feuille source.

        Une feuille clonée depuis BIB/BOEM contient notamment ``drawing r:id``
        et ``pageSetup r:id``. Copier seulement le XML de la feuille sans son
        fichier ``sheetN.xml.rels`` produit un classeur que Microsoft Excel
        signale comme corrompu. Les données, styles, dimensions et fusions sont
        conservés ; seules l'image décorative et les paramètres d'imprimante
        propres à la feuille source sont retirés de la nouvelle feuille.
        """
        relationship_key = f"{{{REL_NS}}}id"
        containers_to_prune = {"hyperlinks", "controls", "oleObjects"}

        def visit(parent: ET.Element):
            for child in list(parent):
                visit(child)
                local_name = child.tag.rsplit("}", 1)[-1]
                if relationship_key not in child.attrib:
                    continue

                if local_name == "pageSetup":
                    child.attrib.pop(relationship_key, None)
                elif local_name == "hyperlink" and child.attrib.get("location"):
                    child.attrib.pop(relationship_key, None)
                else:
                    parent.remove(child)

            for child in list(parent):
                local_name = child.tag.rsplit("}", 1)[-1]
                if local_name in containers_to_prune and len(child) == 0:
                    parent.remove(child)

        visit(root)

    def _register_sheet_in_app_properties(
        self,
        sheet_name: str,
        sheet_count_before: int,
    ):
        """Met à jour docProps/app.xml pour le nouvel onglet."""
        app_path = "docProps/app.xml"
        if app_path not in self.original_entries:
            return

        app_data = self.modified_entries.get(
            app_path, self.original_entries[app_path][1]
        )
        root = ET.fromstring(app_data)

        heading_vector = root.find(
            f"{{{EXT_PROPS_NS}}}HeadingPairs/{{{VT_NS}}}vector"
        )
        if heading_vector is not None:
            items = list(heading_vector)
            for index, item in enumerate(items[:-1]):
                if item.tag != f"{{{VT_NS}}}variant":
                    continue
                label = item.find(f"{{{VT_NS}}}lpstr")
                if label is None or not (label.text or "").lower().startswith(
                    ("feuilles", "worksheets")
                ):
                    continue
                count_node = items[index + 1].find(f"{{{VT_NS}}}i4")
                if count_node is not None:
                    count_node.text = str(sheet_count_before + 1)
                break

        titles_vector = root.find(
            f"{{{EXT_PROPS_NS}}}TitlesOfParts/{{{VT_NS}}}vector"
        )
        if titles_vector is not None:
            title_node = ET.Element(f"{{{VT_NS}}}lpstr")
            title_node.text = sheet_name
            insert_at = min(sheet_count_before, len(list(titles_vector)))
            titles_vector.insert(insert_at, title_node)
            titles_vector.attrib["size"] = str(len(list(titles_vector)))

        self.modified_entries[app_path] = ET.tostring(
            root, encoding="utf-8", xml_declaration=True
        )

    def _next_sheet_path(self) -> str:
        used_numbers = []
        for path in list(self.sheet_paths.values()) + list(self.new_entries.keys()):
            match = re.search(r"xl/worksheets/sheet(\d+)\.xml$", path)
            if match:
                used_numbers.append(int(match.group(1)))

        next_number = (max(used_numbers) + 1) if used_numbers else 1
        return f"xl/worksheets/sheet{next_number}.xml"

    def clone_sheet(self, source_sheet_name: str, new_sheet_name: str) -> str:
        if new_sheet_name in self.sheet_paths:
            return new_sheet_name

        if source_sheet_name not in self.sheet_paths:
            raise HTTPException(
                status_code=500,
                detail=f"Feuille source introuvable pour duplication : {source_sheet_name}",
            )

        source_path = self.sheet_paths[source_sheet_name]
        if source_path in self.original_entries:
            source_data = self.original_entries[source_path][1]
        elif source_path in self.new_entries:
            source_data = self.new_entries[source_path]
        else:
            raise RuntimeError(f"XML source introuvable : {source_path}")

        new_path = self._next_sheet_path()
        source_root = ET.fromstring(source_data)
        self._strip_clone_relationship_references(source_root)
        self.new_entries[new_path] = serialize_ooxml(source_root, source_data)
        self.sheet_paths[new_sheet_name] = new_path

        # 1) workbook.xml : déclaration de la nouvelle feuille
        workbook_path = "xl/workbook.xml"
        workbook_data = self.modified_entries.get(
            workbook_path,
            self.original_entries[workbook_path][1],
        )
        workbook_root = ET.fromstring(workbook_data)
        sheets = workbook_root.find(qn("sheets"))
        if sheets is None:
            raise RuntimeError("workbook.xml ne contient pas de noeud sheets")

        sheet_count_before = len(sheets.findall(qn("sheet")))
        max_sheet_id = 0
        for sheet in sheets.findall(qn("sheet")):
            try:
                max_sheet_id = max(max_sheet_id, int(sheet.attrib.get("sheetId", "0")))
            except Exception:
                pass

        # 2) workbook.xml.rels : relation vers le nouveau worksheet
        rels_path = "xl/_rels/workbook.xml.rels"
        rels_data = self.modified_entries.get(
            rels_path,
            self.original_entries[rels_path][1],
        )
        rels_root = ET.fromstring(rels_data)

        used_rids = []
        for rel in rels_root.findall(f"{{{PACKAGE_REL_NS}}}Relationship"):
            rid = rel.attrib.get("Id", "")
            match = re.match(r"rId(\d+)$", rid)
            if match:
                used_rids.append(int(match.group(1)))
        new_rid = f"rId{(max(used_rids) + 1) if used_rids else 1}"

        ET.SubElement(
            rels_root,
            f"{{{PACKAGE_REL_NS}}}Relationship",
            {
                "Id": new_rid,
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
                "Target": new_path.replace("xl/", ""),
            },
        )

        ET.SubElement(
            sheets,
            qn("sheet"),
            {
                "name": new_sheet_name,
                "sheetId": str(max_sheet_id + 1),
                f"{{{REL_NS}}}id": new_rid,
            },
        )

        self.modified_entries[workbook_path] = serialize_ooxml(
            workbook_root, self.original_entries[workbook_path][1]
        )
        self.modified_entries[rels_path] = ET.tostring(
            rels_root, encoding="utf-8", xml_declaration=True
        )

        # 3) [Content_Types].xml : type de contenu du nouveau worksheet
        content_path = "[Content_Types].xml"
        content_data = self.modified_entries.get(
            content_path,
            self.original_entries[content_path][1],
        )
        content_root = ET.fromstring(content_data)
        part_name = f"/{new_path}"
        exists = any(
            item.attrib.get("PartName") == part_name
            for item in content_root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
        )
        if not exists:
            ET.SubElement(
                content_root,
                f"{{{CONTENT_TYPES_NS}}}Override",
                {
                    "PartName": part_name,
                    "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
                },
            )
        self.modified_entries[content_path] = ET.tostring(
            content_root, encoding="utf-8", xml_declaration=True
        )

        self._register_sheet_in_app_properties(
            new_sheet_name, sheet_count_before
        )

        return new_sheet_name

    def _get_or_create_row(self, root: ET.Element, row_number: int) -> ET.Element:
        sheet_data = root.find(qn("sheetData"))
        if sheet_data is None:
            sheet_data = ET.SubElement(root, qn("sheetData"))

        for row in sheet_data.findall(qn("row")):
            current = int(row.attrib.get("r", "0"))
            if current == row_number:
                return row
            if current > row_number:
                new_row = ET.Element(qn("row"), {"r": str(row_number)})
                sheet_data.insert(list(sheet_data).index(row), new_row)
                return new_row

        return ET.SubElement(sheet_data, qn("row"), {"r": str(row_number)})

    def _get_or_create_cell(self, root: ET.Element, cell_ref: str) -> ET.Element:
        match = re.match(r"[A-Z]+(\d+)$", cell_ref.upper())
        if not match:
            raise ValueError(f"Référence cellule invalide : {cell_ref}")

        row = self._get_or_create_row(root, int(match.group(1)))
        wanted_column = column_number(cell_ref)

        for cell in row.findall(qn("c")):
            ref = cell.attrib.get("r", "")
            if ref.upper() == cell_ref.upper():
                return cell
            if ref and column_number(ref) > wanted_column:
                new_cell = ET.Element(qn("c"), {"r": cell_ref.upper()})
                row.insert(list(row).index(cell), new_cell)
                return new_cell

        return ET.SubElement(row, qn("c"), {"r": cell_ref.upper()})

    @staticmethod
    def _clear_payload(cell: ET.Element):
        for child in list(cell):
            if child.tag in {qn("f"), qn("v"), qn("is")}:
                cell.remove(child)
        cell.attrib.pop("t", None)

    def clear_cell(self, sheet_name: str, cell_ref: str):
        root = self.require_sheet(sheet_name)
        cell = self._get_or_create_cell(root, cell_ref)
        self._clear_payload(cell)

    def set_number(self, sheet_name: str, cell_ref: str, value):
        if value is None:
            self.clear_cell(sheet_name, cell_ref)
            return

        root = self.require_sheet(sheet_name)
        cell = self._get_or_create_cell(root, cell_ref)
        self._clear_payload(cell)
        numeric = float(value)
        text_value = str(int(numeric)) if numeric.is_integer() else format(numeric, ".15g")
        ET.SubElement(cell, qn("v")).text = text_value

    def set_date(self, sheet_name: str, cell_ref: str, value: date):
        self.set_number(sheet_name, cell_ref, excel_serial(value, self.date_1904))

    def set_text(self, sheet_name: str, cell_ref: str, value: str | None):
        if value is None:
            self.clear_cell(sheet_name, cell_ref)
            return

        root = self.require_sheet(sheet_name)
        cell = self._get_or_create_cell(root, cell_ref)
        self._clear_payload(cell)
        cell.attrib["t"] = "inlineStr"
        inline_string = ET.SubElement(cell, qn("is"))
        text_element = ET.SubElement(inline_string, qn("t"))
        text_element.text = str(value)

    def _prepare_workbook_xml(self):
        workbook_path = "xl/workbook.xml"
        root = ET.fromstring(
            self.modified_entries.get(workbook_path, self.original_entries[workbook_path][1])
        )
        calc_pr = root.find(qn("calcPr"))
        if calc_pr is None:
            calc_pr = ET.SubElement(root, qn("calcPr"))
        calc_pr.attrib["calcMode"] = "auto"
        calc_pr.attrib["fullCalcOnLoad"] = "1"
        calc_pr.attrib["forceFullCalc"] = "1"
        self.modified_entries["xl/workbook.xml"] = serialize_ooxml(
            root, self.original_entries["xl/workbook.xml"][1]
        )

    def _remove_calc_chain_references(self):
        rels_path = "xl/_rels/workbook.xml.rels"
        rels_root = ET.fromstring(
            self.modified_entries.get(rels_path, self.original_entries[rels_path][1])
        )
        for item in list(rels_root):
            if item.attrib.get("Type", "").endswith("/calcChain"):
                rels_root.remove(item)
        self.modified_entries[rels_path] = ET.tostring(
            rels_root, encoding="utf-8", xml_declaration=True
        )

        content_path = "[Content_Types].xml"
        content_root = ET.fromstring(
            self.modified_entries.get(content_path, self.original_entries[content_path][1])
        )
        for item in list(content_root):
            if item.attrib.get("PartName") == "/xl/calcChain.xml":
                content_root.remove(item)
        self.modified_entries[content_path] = ET.tostring(
            content_root, encoding="utf-8", xml_declaration=True
        )

    def save(self, output_path: Path):
        for sheet_name, root in self.sheet_roots.items():
            path = self.sheet_paths[sheet_name]

            # Ancienne feuille existante dans le modèle Excel :
            # on garde la sérialisation spéciale qui respecte le format original.
            if path in self.original_entries:
                self.modified_entries[path] = serialize_ooxml(
                    root, self.original_entries[path][1]
                )

            # Nouvelle feuille créée dynamiquement, par exemple TEST_BARRAGE_01 :
            # elle n'existe pas dans original_entries, donc il ne faut pas chercher
            # self.original_entries[path], sinon KeyError: xl/worksheets/sheetXX.xml.
            else:
                self.modified_entries[path] = ET.tostring(
                    root,
                    encoding="utf-8",
                    xml_declaration=True,
                )

        self._prepare_workbook_xml()
        self._remove_calc_chain_references()

        with ZipFile(output_path, "w", compression=ZIP_DEFLATED, allowZip64=True) as target:
            for filename, (info, original_data) in self.original_entries.items():
                if filename == "xl/calcChain.xml":
                    continue
                data = self.modified_entries.get(filename, original_data)
                target.writestr(info, data)

            for filename, original_data in self.new_entries.items():
                if filename in self.original_entries:
                    continue
                data = self.modified_entries.get(filename, original_data)
                target.writestr(filename, data)

        try:
            validate_xlsx_package(output_path)
        except Exception:
            output_path.unlink(missing_ok=True)
            raise


def clear_data_row(editor: XlsxTemplateEditor, sheet_name: str, row: int, last_column: str):
    last_index = column_number(last_column)

    def column_name(index: int) -> str:
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    for column_index in range(2, last_index + 1):
        editor.clear_cell(sheet_name, f"{column_name(column_index)}{row}")


def fill_monthly_sheet(editor: XlsxTemplateEditor, code: str, config: dict, raw: dict):
    context = raw["context"]
    bilans = raw["bilans"]
    restitutions = raw["restitutions"]
    specials = raw["specials"]
    sheet_name = config["sheet_name"]

    editor.set_text(
        sheet_name,
        "A4",
        f"{MONTH_NAMES_FR_UPPER[context['month']]} {context['year']}",
    )

    for offset, day in enumerate(month_dates(context["month_start"])):
        row_number = config["data_start_row"] + offset
        day_key = day.isoformat()
        bilan = bilans.get((code, day_key))
        restitution_values = restitutions.get((code, day_key), {})
        special_values = specials.get((code, day_key), {})

        clear_data_row(editor, sheet_name, row_number, config["last_column"])
        editor.set_date(sheet_name, f"A{row_number}", day)

        if not bilan:
            continue

        editor.set_number(sheet_name, f"B{row_number}", bilan.get("cote_7h_ngm"))
        editor.set_number(sheet_name, f"C{row_number}", bilan.get("volume_mm3"))
        editor.set_number(sheet_name, f"D{row_number}", bilan.get("hauteur_bac_mm"))
        editor.set_number(sheet_name, f"E{row_number}", bilan.get("pluie_mm"))
        editor.set_number(sheet_name, f"F{row_number}", bilan.get("evaporation_m3"))

        restitution_present = False
        restitution_sum = 0.0

        for type_code, column in config["restitutions"].items():
            if type_code in restitution_values:
                value = float(restitution_values[type_code])
                editor.set_number(sheet_name, f"{column}{row_number}", value)
                restitution_present = True
                restitution_sum += value

        total = bilan.get("total_restitutions_m3")
        if total is None and restitution_present:
            total = restitution_sum
        editor.set_number(sheet_name, f"{config['total_restitutions']}{row_number}", total)

        apports = bilan.get("apports_raw_m3")
        if apports is None:
            apports = bilan.get("apports_m3")
        editor.set_number(sheet_name, f"{config['apports']}{row_number}", apports)

        for special_code, column in config["specials"].items():
            special_value = special_values.get(special_code)
            if special_code == "TRANSFERT_DAR_KHROFA" and special_value is None:
                special_value = bilan.get("transfert_dar_khrofa_m3")
            editor.set_number(sheet_name, f"{column}{row_number}", special_value)

    fill_totals(editor, code, config, raw)


def _month_bilans_for_code(code: str, raw: dict) -> list[tuple[dict, dict, dict]]:
    context = raw["context"]
    result = []
    day = context["month_start"]

    while day < context["next_month_start"]:
        day_key = day.isoformat()
        bilan = raw["bilans"].get((code, day_key))
        if bilan:
            result.append(
                (
                    bilan,
                    raw["restitutions"].get((code, day_key), {}),
                    raw["specials"].get((code, day_key), {}),
                )
            )
        day += timedelta(days=1)

    return result


def fill_totals(editor: XlsxTemplateEditor, code: str, config: dict, raw: dict):
    rows = _month_bilans_for_code(code, raw)
    total_row = config["total_row"]
    sheet_name = config["sheet_name"]

    rainfall_total = sum((bilan.get("pluie_mm") or 0.0) for bilan, _, _ in rows)
    evaporation_total = sum((bilan.get("evaporation_m3") or 0.0) for bilan, _, _ in rows)

    editor.set_number(sheet_name, f"E{total_row}", rainfall_total)
    editor.set_number(sheet_name, f"F{total_row}", evaporation_total / 1_000_000.0)

    for type_code, column in config["restitutions"].items():
        total = sum(rest_values.get(type_code, 0.0) for _, rest_values, _ in rows)
        editor.set_number(sheet_name, f"{column}{total_row}", total / 1_000_000.0)

    total_restitutions = sum(
        (
            bilan.get("total_restitutions_m3")
            if bilan.get("total_restitutions_m3") is not None
            else sum(rest_values.values())
        )
        or 0.0
        for bilan, rest_values, _ in rows
    )
    editor.set_number(
        sheet_name,
        f"{config['total_restitutions']}{total_row}",
        total_restitutions / 1_000_000.0,
    )

    apports_total = 0.0
    for bilan, _, _ in rows:
        value = bilan.get("apports_raw_m3")
        if value is None:
            value = bilan.get("apports_m3")
        apports_total += value or 0.0

    editor.set_number(
        sheet_name,
        f"{config['apports']}{total_row}",
        max(0.0, apports_total) / 1_000_000.0,
    )

    for special_code, column in config["specials"].items():
        if special_code in {"BGE_GARDE_AM", "BGE_GARDE_AV"}:
            editor.clear_cell(sheet_name, f"{column}{total_row}")
            continue

        if special_code == "TRANSFERT_DAR_KHROFA":
            total = sum(
                special_values.get(
                    special_code,
                    bilan.get("transfert_dar_khrofa_m3") or 0.0,
                )
                for bilan, _, special_values in rows
            )
        else:
            total = sum(
                special_values.get(special_code, 0.0)
                for _, _, special_values in rows
            )

        if special_code == "BGE_GARDE_PLUIE":
            editor.set_number(sheet_name, f"{column}{total_row}", total)
        else:
            editor.set_number(sheet_name, f"{column}{total_row}", total / 1_000_000.0)


def fill_home_sheet(editor: XlsxTemplateEditor, raw: dict):
    context = raw["context"]
    editor.set_number("PAGE D'ACCEUIL", "F8", context["month"])
    editor.set_number("PAGE D'ACCEUIL", "F9", context["year"])


def fill_crues_sheet(editor: XlsxTemplateEditor, raw: dict):
    context = raw["context"]
    bilans = raw["bilans"]
    sheet_name = "ANNONCE DE CRUES"

    editor.set_date(sheet_name, "F4", context["date_situation"])
    editor.set_date(sheet_name, "F5", context["date_interval"])

    for code, row_number in CRUES_BARRAGE_ROWS.items():
        current = bilans.get((code, context["date_situation"].isoformat())) or {}
        interval = bilans.get((code, context["date_interval"].isoformat())) or {}

        editor.set_number(sheet_name, f"C{row_number}", interval.get("pluie_mm"))
        editor.set_number(sheet_name, f"D{row_number}", current.get("cote_7h_ngm"))
        editor.set_number(sheet_name, f"F{row_number}", current.get("volume_mm3"))

        monthly_rain = 0.0
        found_rain = False
        day = context["month_start"]
        while day < context["next_month_start"]:
            bilan = bilans.get((code, day.isoformat()))
            if bilan and bilan.get("pluie_mm") is not None:
                monthly_rain += float(bilan["pluie_mm"])
                found_rain = True
            day += timedelta(days=1)

        editor.set_number(sheet_name, f"T{row_number}", monthly_rain if found_rain else None)




# ============================================================
# FEUILLES DYNAMIQUES POUR LES BARRAGES AJOUTÉS - NIVEAU 2 PROPRE
# ============================================================

def excel_column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def excel_column_index(column_name: str) -> int:
    result = 0
    for char in column_name.upper():
        result = result * 26 + ord(char) - 64
    return result


def cell_to_row_col(cell_ref: str) -> tuple[int, int]:
    match = re.match(r"^([A-Z]+)(\d+)$", cell_ref.upper())
    if not match:
        raise ValueError(f"Cellule invalide : {cell_ref}")
    return int(match.group(2)), excel_column_index(match.group(1))


def range_to_bounds(range_ref: str) -> tuple[int, int, int, int]:
    if ":" in range_ref:
        start_ref, end_ref = range_ref.split(":", 1)
    else:
        start_ref = end_ref = range_ref

    start_row, start_col = cell_to_row_col(start_ref)
    end_row, end_col = cell_to_row_col(end_ref)

    return (
        min(start_row, end_row),
        max(start_row, end_row),
        min(start_col, end_col),
        max(start_col, end_col),
    )


def ranges_intersect(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    a_min_row, a_max_row, a_min_col, a_max_col = a
    b_min_row, b_max_row, b_min_col, b_max_col = b

    return not (
        a_max_row < b_min_row
        or b_max_row < a_min_row
        or a_max_col < b_min_col
        or b_max_col < a_min_col
    )


def remove_merges_intersecting(
    editor: XlsxTemplateEditor,
    sheet_name: str,
    min_row: int,
    max_row: int,
    min_col: int,
    max_col: int,
):
    root = editor.require_sheet(sheet_name)
    merge_cells = root.find(qn("mergeCells"))

    if merge_cells is None:
        return

    target = (min_row, max_row, min_col, max_col)

    for merge_cell in list(merge_cells):
        ref = merge_cell.attrib.get("ref")
        if not ref:
            continue

        try:
            bounds = range_to_bounds(ref)
        except Exception:
            continue

        if ranges_intersect(bounds, target):
            merge_cells.remove(merge_cell)

    remaining = list(merge_cells)
    if remaining:
        merge_cells.attrib["count"] = str(len(remaining))
    else:
        root.remove(merge_cells)


def add_merge(editor: XlsxTemplateEditor, sheet_name: str, start_ref: str, end_ref: str):
    if start_ref.upper() == end_ref.upper():
        return

    root = editor.require_sheet(sheet_name)
    merge_ref = f"{start_ref.upper()}:{end_ref.upper()}"

    merge_cells = root.find(qn("mergeCells"))
    if merge_cells is None:
        merge_cells = ET.Element(qn("mergeCells"))
        sheet_data = root.find(qn("sheetData"))

        if sheet_data is not None:
            root.insert(list(root).index(sheet_data) + 1, merge_cells)
        else:
            root.append(merge_cells)

    for item in merge_cells.findall(qn("mergeCell")):
        if item.attrib.get("ref") == merge_ref:
            return

    ET.SubElement(merge_cells, qn("mergeCell"), {"ref": merge_ref})
    merge_cells.attrib["count"] = str(len(merge_cells.findall(qn("mergeCell"))))


def copy_cell_style(
    editor: XlsxTemplateEditor,
    sheet_name: str,
    source_ref: str,
    target_ref: str,
):
    root = editor.require_sheet(sheet_name)
    source = editor._get_or_create_cell(root, source_ref)
    target = editor._get_or_create_cell(root, target_ref)

    if "s" in source.attrib:
        target.attrib["s"] = source.attrib["s"]


def set_columns_width(
    editor: XlsxTemplateEditor,
    sheet_name: str,
    start_col: int,
    end_col: int,
    width: float,
):
    if start_col > end_col:
        return

    root = editor.require_sheet(sheet_name)

    cols = root.find(qn("cols"))
    if cols is None:
        cols = ET.Element(qn("cols"))
        sheet_data = root.find(qn("sheetData"))
        if sheet_data is not None:
            root.insert(list(root).index(sheet_data), cols)
        else:
            root.insert(0, cols)

    attrs = {
        "min": str(start_col),
        "max": str(end_col),
        "width": str(width),
        "customWidth": "1",
    }

    if width <= 0:
        attrs["hidden"] = "1"

    ET.SubElement(cols, qn("col"), attrs)


def set_columns_hidden(editor: XlsxTemplateEditor, sheet_name: str, start_col: int, end_col: int):
    set_columns_width(editor, sheet_name, start_col, end_col, 0)


def clear_row_range(
    editor: XlsxTemplateEditor,
    sheet_name: str,
    row_number: int,
    start_col: int,
    end_col: int,
):
    for col_index in range(start_col, end_col + 1):
        editor.clear_cell(sheet_name, f"{excel_column_name(col_index)}{row_number}")


def clear_dynamic_template_zone(editor: XlsxTemplateEditor, sheet_name: str, config: dict):
    cleanup_last_col = config["cleanup_last_col_index"]
    group_row = config["group_row"]
    header_row = config["header_row"]

    clear_row_range(editor, sheet_name, group_row, 7, cleanup_last_col)
    clear_row_range(editor, sheet_name, header_row, 7, cleanup_last_col)

    for offset in range(DATA_ROW_COUNT):
        clear_row_range(
            editor,
            sheet_name,
            config["data_start_row"] + offset,
            2,
            cleanup_last_col,
        )

    clear_row_range(editor, sheet_name, config["total_row"], 2, cleanup_last_col)


def safe_excel_sheet_name(raw_name: str, existing_names: set[str]) -> str:
    clean = re.sub(r"[\\/\?\*\[\]:]", "_", str(raw_name or "BARRAGE"))
    clean = clean.strip() or "BARRAGE"
    clean = clean[:31]

    candidate = clean
    counter = 1

    while candidate in existing_names:
        suffix = f"_{counter}"
        candidate = f"{clean[:31 - len(suffix)]}{suffix}"
        counter += 1

    existing_names.add(candidate)
    return candidate


def clean_barrage_title(barrage_nom: str | None, code: str) -> str:
    text = str(barrage_nom or code).strip()
    text = re.sub(r"^\s*barrage\s+", "", text, flags=re.IGNORECASE)
    return f"BARRAGE {text.upper()}"


def build_dynamic_sheet_config(code: str, raw: dict) -> dict:
    restitution_items = raw.get("barrage_restitutions", {}).get(code, [])
    restitution_codes = [item["type_code"] for item in restitution_items]

    if len(restitution_codes) <= 7:
        source_sheet = "BIB"
        data_start_row = 8
        total_row = 41
        cleanup_last_col_index = 15
    else:
        source_sheet = "BOEM"
        data_start_row = 9
        total_row = 42
        cleanup_last_col_index = 20

    group_row = data_start_row - 2
    header_row = data_start_row - 1

    restitution_start_col = 7
    restitutions = {}

    for offset, type_code in enumerate(restitution_codes):
        col_index = restitution_start_col + offset
        restitutions[type_code] = excel_column_name(col_index)

    restitution_count = len(restitutions)
    total_col_index = restitution_start_col + restitution_count
    apports_col_index = total_col_index + 1

    cleanup_last_col_index = max(cleanup_last_col_index, apports_col_index + 2)

    return {
        "source_sheet": source_sheet,
        "sheet_name": code,
        "data_start_row": data_start_row,
        "total_row": total_row,
        "last_column": excel_column_name(cleanup_last_col_index),
        "cleanup_last_col_index": cleanup_last_col_index,
        "group_row": group_row,
        "header_row": header_row,
        "restitution_start_col": restitution_start_col,
        "restitution_end_col": restitution_start_col + restitution_count - 1,
        "total_col_index": total_col_index,
        "apports_col_index": apports_col_index,
        "output_last_col_index": apports_col_index,
        "restitutions": restitutions,
        "total_restitutions": excel_column_name(total_col_index),
        "apports": excel_column_name(apports_col_index),
        "specials": {},
    }


def fill_dynamic_sheet_headers(editor: XlsxTemplateEditor, code: str, config: dict, raw: dict):
    sheet_name = config["sheet_name"]
    barrage = raw.get("barrages", {}).get(code, {})
    barrage_nom = barrage.get("nom") or code

    group_row = config["group_row"]
    header_row = config["header_row"]
    cleanup_last_col = config["cleanup_last_col_index"]

    editor.set_text(sheet_name, "A2", clean_barrage_title(barrage_nom, code))
    editor.set_text(sheet_name, "A3", "BILAN HYDRAULIQUE JOURNALIER")
    editor.set_text(
        sheet_name,
        "A4",
        f"{MONTH_NAMES_FR_UPPER[raw['context']['month']]} {raw['context']['year']}",
    )

    remove_merges_intersecting(
        editor,
        sheet_name,
        min_row=group_row,
        max_row=header_row,
        min_col=7,
        max_col=cleanup_last_col,
    )

    clear_dynamic_template_zone(editor, sheet_name, config)

    fixed_headers = {
        "A": "Date",
        "B": "Cote à 7h\n(NGM)",
        "C": "Volume\n(Mm³)",
        "D": "Hauteur\nBac (mm)",
        "E": "Pluie\n(mm)",
        "F": "Evaporation\n(m³)",
    }

    for col, label in fixed_headers.items():
        editor.set_text(sheet_name, f"{col}{group_row}", label)

    label_by_type = {
        item["type_code"]: item.get("libelle") or item["type_code"]
        for item in raw.get("barrage_restitutions", {}).get(code, [])
    }

    if config["restitutions"]:
        start_col = config["restitution_start_col"]
        end_col = config["restitution_end_col"]

        editor.set_text(sheet_name, f"{excel_column_name(start_col)}{group_row}", "Restitutions")
        add_merge(
            editor,
            sheet_name,
            f"{excel_column_name(start_col)}{group_row}",
            f"{excel_column_name(end_col)}{group_row}",
        )

        for type_code, col in config["restitutions"].items():
            editor.set_text(sheet_name, f"{col}{header_row}", label_by_type.get(type_code, type_code))

    # Colonnes indépendantes : elles ne doivent pas être sous le titre Restitutions.
    # Elles sont fusionnées verticalement comme Date/Cote/Volume.
    total_col = config["total_restitutions"]
    apports_col = config["apports"]

    editor.set_text(sheet_name, f"{total_col}{group_row}", "Total restitutions")
    editor.clear_cell(sheet_name, f"{total_col}{header_row}")
    add_merge(editor, sheet_name, f"{total_col}{group_row}", f"{total_col}{header_row}")

    editor.set_text(sheet_name, f"{apports_col}{group_row}", "Apports")
    editor.clear_cell(sheet_name, f"{apports_col}{header_row}")
    add_merge(editor, sheet_name, f"{apports_col}{group_row}", f"{apports_col}{header_row}")

    first_unused_col = config["output_last_col_index"] + 1
    if first_unused_col <= cleanup_last_col:
        set_columns_hidden(editor, sheet_name, first_unused_col, cleanup_last_col)


def fill_dynamic_barrage_sheet(
    editor: XlsxTemplateEditor,
    code: str,
    raw: dict,
    existing_sheet_names: set[str],
):
    config = build_dynamic_sheet_config(code, raw)
    sheet_name = safe_excel_sheet_name(code, existing_sheet_names)
    config["sheet_name"] = sheet_name

    editor.clone_sheet(config["source_sheet"], sheet_name)
    fill_dynamic_sheet_headers(editor, code, config, raw)
    fill_monthly_sheet(editor, code, config, raw)


# ============================================================
# BARÈMES DYNAMIQUES DANS LA FEUILLE "Baréms des barrages"
# ============================================================

BAREMES_SHEET_NAME = "Baréms des barrages"


def write_dynamic_bareme_block(
    editor: XlsxTemplateEditor,
    code: str,
    block_start_col: int,
    points: list[dict],
    raw: dict,
):
    if not points:
        return

    if BAREMES_SHEET_NAME not in editor.sheet_paths:
        return

    title_col = excel_column_name(block_start_col)
    surface_col = excel_column_name(block_start_col + 1)
    volume_col = excel_column_name(block_start_col + 2)

    barrage = raw.get("barrages", {}).get(code, {})
    title = f"{str(barrage.get('nom') or code).replace('Barrage ', '').replace('barrage ', '')} (plateforme)"

    # Copier le style du premier bloc officiel BOEM.
    for target_col_index, source_col in zip(
        [block_start_col, block_start_col + 1, block_start_col + 2],
        ["A", "B", "C"],
    ):
        target_col = excel_column_name(target_col_index)
        for row in range(1, max(3 + len(points), 10)):
            copy_cell_style(
                editor,
                BAREMES_SHEET_NAME,
                f"{source_col}{min(row, 10)}",
                f"{target_col}{row}",
            )

    remove_merges_intersecting(
        editor,
        BAREMES_SHEET_NAME,
        min_row=1,
        max_row=1,
        min_col=block_start_col,
        max_col=block_start_col + 2,
    )
    add_merge(editor, BAREMES_SHEET_NAME, f"{title_col}1", f"{volume_col}1")

    editor.set_text(BAREMES_SHEET_NAME, f"{title_col}1", title)
    editor.set_text(BAREMES_SHEET_NAME, f"{title_col}2", "Côte\n(NGM)")
    editor.set_text(BAREMES_SHEET_NAME, f"{surface_col}2", "surface")
    editor.set_text(BAREMES_SHEET_NAME, f"{volume_col}2", "volume\n(Mm³)")

    # Nettoyer les anciennes valeurs éventuelles de ce bloc.
    for row in range(3, 3 + max(len(points), 500)):
        editor.clear_cell(BAREMES_SHEET_NAME, f"{title_col}{row}")
        editor.clear_cell(BAREMES_SHEET_NAME, f"{surface_col}{row}")
        editor.clear_cell(BAREMES_SHEET_NAME, f"{volume_col}{row}")

    for offset, point in enumerate(points):
        row = 3 + offset
        editor.set_number(BAREMES_SHEET_NAME, f"{title_col}{row}", point.get("cote_ngm"))
        editor.set_number(BAREMES_SHEET_NAME, f"{surface_col}{row}", point.get("surface_km2"))
        editor.set_number(BAREMES_SHEET_NAME, f"{volume_col}{row}", point.get("volume_mm3"))

    set_columns_width(editor, BAREMES_SHEET_NAME, block_start_col, block_start_col + 2, 12)


def fill_dynamic_baremes_sheet(editor: XlsxTemplateEditor, raw: dict):
    dynamic_codes = raw.get("dynamic_codes", [])
    if not dynamic_codes:
        return

    bareme_points = raw.get("bareme_points", {})
    official_block_count = len(TARGET_BARRAGE_CODES)
    first_dynamic_col = official_block_count * 3 + 1

    for index, code in enumerate(dynamic_codes):
        points = bareme_points.get(code, [])
        if not points:
            continue

        block_start_col = first_dynamic_col + index * 3
        write_dynamic_bareme_block(editor, code, block_start_col, points, raw)


def generate_annonce_excel(db: Session, date_situation: date) -> Path:
    raw = load_annonce_data(db, date_situation)
    context = raw["context"]

    template_path = resolve_template_path()
    output_dir = resolve_exports_dir()
    filename = (
        f"Annonce barrages - {context['year']}-{context['month']:02d} "
        f"- {uuid4().hex[:8]}.xlsx"
    )
    output_path = output_dir / filename

    editor = XlsxTemplateEditor(template_path)
    fill_home_sheet(editor, raw)
    fill_crues_sheet(editor, raw)

    official_codes = raw.get("official_codes") or TARGET_BARRAGE_CODES
    for code in official_codes:
        if code in SHEET_CONFIGS:
            fill_monthly_sheet(editor, code, SHEET_CONFIGS[code], raw)

    existing_sheet_names = set(editor.sheet_paths.keys())
    for code in raw.get("dynamic_codes", []):
        fill_dynamic_barrage_sheet(editor, code, raw, existing_sheet_names)

    fill_dynamic_baremes_sheet(editor, raw)

    editor.save(output_path)

    try:
        register_export(
            db,
            date_situation=date_situation,
            month=context["month"],
            year=context["year"],
            filename=filename,
            output_path=output_path,
        )
        db.commit()
    except Exception:
        db.rollback()
        # L'export reste disponible même si son historisation échoue.

    return output_path

# === ABHL V25 ANNONCE OFFICIAL ENGINE START ===
# Moteur Annonce officiel général : règles tirées du workflow Excel agence.
# Aucune date ni valeur de juin n'est codée en dur.

_ABHL_V25_SYNTHETIC_COTE_FLAG = "ANNONCE_COTE_SOURCE_MISSING"
_ABHL_V25_FIELD_BLANK_PREFIX = "ANNONCE_FIELD_BLANK__"
_ABHL_V25_REST_OVERRIDE_PREFIX = "ANNONCE_REST_OVERRIDE__"
_ABHL_V25_REST_BLANK_PREFIX = "ANNONCE_REST_BLANK__"
_ABHL_V25_SPECIAL_OVERRIDE_PREFIX = "ANNONCE_SPECIAL_OVERRIDE__"
_ABHL_V25_SPECIAL_BLANK_PREFIX = "ANNONCE_SPECIAL_BLANK__"
_ABHL_V25_CRUES_VOLUME_VISIBLE = {
    "NAKHLA", "CAI", "MHB_MEHDI", "SMIR", "CHEFCHAOUEN",
    "TANGER_MED", "DAR_KHROFA", "KHATTABI", "JOUMOUA",
}
_ABHL_V25_CRUES_AGITE_IF_MISSING = {"BIB", "KHARROUB"}
_ABHL_V25_CRUES_VOLUME_DECIMALS = {"DAR_KHROFA": 2}


def _abhl_v25_num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _abhl_v25_truthy(value) -> bool:
    numeric = _abhl_v25_num(value)
    return numeric is not None and abs(numeric) > 1e-12


def _abhl_v25_first(mapping: dict, *keys: str):
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return _abhl_v25_num(mapping.get(key))
    return None


def _abhl_v25_sum_present(mapping: dict, *keys: str):
    values = []
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            value = _abhl_v25_num(mapping.get(key))
            if value is not None:
                values.append(value)
    return sum(values) if values else None


def _abhl_v25_restitution_value(code: str, visible_code: str, values: dict):
    """Résout anciens/nouveaux codes sans perdre l'historique."""
    exact = _abhl_v25_first(values, visible_code)
    if exact is not None:
        return exact

    if code == "BIB":
        if visible_code == "AEPI":
            return _abhl_v25_first(values, "AEPI_PRISES")
        if visible_code == "JETS_CREUX":
            return _abhl_v25_first(values, "AEPI_JETS_CREUX", "JETS_CREUX")

    if code == "DAR_KHROFA":
        if visible_code == "PRISE_AGRICOLE":
            return _abhl_v25_sum_present(values, "PRISE_AGRICOLE_RD", "PRISE_AGRICOLE_RG")
        if visible_code == "AEPI_PRISES":
            return _abhl_v25_first(values, "AEPI", "AEPI_PRISES")

    if code == "BOEM":
        if visible_code == "IRRIGATION_LOUKKOS_PRISE_AGRICOLE":
            return _abhl_v25_first(values, "IRRIGATION_LOUKKOS_PRISE", "IRRIGATION_LOUKKOS_PRISE_AGRICOLE")
        if visible_code == "TRANSFERT":
            return _abhl_v25_first(values, "TRANSFERT_DAR_KHROFA", "TRANSFERT")
        if visible_code == "VDF":
            split = _abhl_v25_sum_present(values, "VDF_RD", "VDF_RG")
            return split if split is not None else _abhl_v25_first(values, "VDF")

    if code == "KHATTABI":
        if visible_code == "PRISE_AGRICOLE_AM":
            return _abhl_v25_first(values, "PRISE_AGRICOLE_RD", "PRISE_AGRICOLE_AM")
        if visible_code == "PRISE_AGRICOLE_AV":
            return _abhl_v25_first(values, "PRISE_AGRICOLE_RG", "PRISE_AGRICOLE_AV")

    if visible_code == "AEPI":
        # Pour les barrages ayant une seule colonne AEPI, les nouvelles données
        # peuvent être détaillées en prises/jets.
        combined = _abhl_v25_sum_present(values, "AEPI_PRISES", "AEPI_JETS_CREUX")
        if combined is not None:
            return combined
        return _abhl_v25_first(values, "AEPI_PRISES")

    if visible_code == "VDF":
        combined = _abhl_v25_sum_present(values, "VDF_RD", "VDF_RG")
        if combined is not None:
            return combined

    return None


def _abhl_v25_day_key(day: date) -> str:
    return day.isoformat()


def _abhl_v25_specials(code: str, day: date, raw: dict) -> dict:
    return raw["specials"].get((code, _abhl_v25_day_key(day)), {}) or {}


def _abhl_v25_bilan(code: str, day: date, raw: dict) -> dict:
    return raw["bilans"].get((code, _abhl_v25_day_key(day))) or {}


def _abhl_v25_restitutions(code: str, day: date, raw: dict) -> dict:
    return raw["restitutions"].get((code, _abhl_v25_day_key(day)), {}) or {}


def _abhl_v25_field(code: str, day: date, raw: dict, field: str):
    bilan = _abhl_v25_bilan(code, day, raw)
    if not bilan:
        return None
    flags = _abhl_v25_specials(code, day, raw)
    if _abhl_v25_truthy(flags.get(_ABHL_V25_FIELD_BLANK_PREFIX + field)):
        return None
    return _abhl_v25_num(bilan.get(field))


def _abhl_v25_cote(code: str, day: date, raw: dict):
    bilan = _abhl_v25_bilan(code, day, raw)
    if not bilan:
        return None
    flags = _abhl_v25_specials(code, day, raw)
    if _abhl_v25_truthy(flags.get(_ABHL_V25_SYNTHETIC_COTE_FLAG)):
        return None
    return _abhl_v25_num(bilan.get("cote_7h_ngm"))


def _abhl_v25_bareme_point(code: str, cote, raw: dict):
    cote = _abhl_v25_num(cote)
    if cote is None:
        return None
    cache = raw.setdefault("_abhl_v25_bareme_cache", {})
    cache_key = (code, round(cote, 6))
    if cache_key in cache:
        return cache[cache_key]

    best = None
    best_delta = None
    for point in raw.get("bareme_points", {}).get(code, []) or []:
        pc = _abhl_v25_num(point.get("cote_ngm"))
        if pc is None:
            continue
        delta = abs(pc - cote)
        if best_delta is None or delta < best_delta:
            best, best_delta = point, delta
            if delta <= 1e-10:
                break

    # Excel agence fait un SUMIF exact. On tolère uniquement le bruit flottant.
    if best is not None and best_delta is not None and best_delta <= 1e-6:
        cache[cache_key] = best
        return best
    cache[cache_key] = None
    return None


def _abhl_v25_volume_surface(code: str, day: date, raw: dict):
    bilan = _abhl_v25_bilan(code, day, raw)
    cote = _abhl_v25_cote(code, day, raw)
    if cote is None:
        return None, None, None

    point = _abhl_v25_bareme_point(code, cote, raw)
    if point:
        volume = _abhl_v25_num(point.get("volume_mm3"))
        surface = _abhl_v25_num(point.get("surface_km2"))
    else:
        # Repli de sécurité si le barème importé ne possède pas exactement la cote.
        # On n'interpole jamais.
        volume = _abhl_v25_num(bilan.get("volume_mm3"))
        surface = _abhl_v25_num(bilan.get("surface_km2"))
    return cote, volume, surface


def _abhl_v25_special_value(code: str, special_code: str, day: date, raw: dict, visible_rest: dict, next_cote):
    special_values = _abhl_v25_specials(code, day, raw)
    restitution_values = _abhl_v25_restitutions(code, day, raw)

    if _abhl_v25_truthy(special_values.get(_ABHL_V25_SPECIAL_BLANK_PREFIX + special_code)):
        return None
    override_code = _ABHL_V25_SPECIAL_OVERRIDE_PREFIX + special_code
    if override_code in special_values:
        return _abhl_v25_num(special_values.get(override_code))

    if code == "DAR_KHROFA":
        if special_code == "UTILISATION_AEPI_TANGER":
            return _abhl_v25_first(special_values, special_code) if special_code in special_values else _abhl_v25_first(restitution_values, "AEPI_TANGER")
        if special_code == "UTILISATION_IRRIGATION":
            prise = visible_rest.get("PRISE_AGRICOLE")
            aepi_tanger = _abhl_v25_special_value(code, "UTILISATION_AEPI_TANGER", day, raw, visible_rest, next_cote)
            if prise is not None and aepi_tanger is not None:
                return prise - aepi_tanger
            fallback = _abhl_v25_first(special_values, special_code)
            if fallback is not None:
                return fallback
            return _abhl_v25_first(restitution_values, "IRRIGATION")
        if special_code == "TRANSFERT_DAR_KHROFA":
            # Dans l'Excel agence : si la cote suivante existe, la cellule prend
            # le transfert BOEM du même jour; une cellule source vide vaut 0.
            if next_cote is None:
                return None
            boem_values = _abhl_v25_restitutions("BOEM", day, raw)
            transfer = _abhl_v25_restitution_value("BOEM", "TRANSFERT", boem_values)
            return 0.0 if transfer is None else transfer

    return _abhl_v25_first(special_values, special_code)


def _abhl_v25_model_row(code: str, day: date, config: dict, raw: dict) -> dict:
    bilan = _abhl_v25_bilan(code, day, raw)
    cote, volume, surface = _abhl_v25_volume_surface(code, day, raw)
    next_cote, next_volume, next_surface = _abhl_v25_volume_surface(code, day + timedelta(days=1), raw)

    bac = _abhl_v25_field(code, day, raw, "hauteur_bac_mm")
    pluie = _abhl_v25_field(code, day, raw, "pluie_mm")

    # Formule agence : F = ((bac + pluie) * 0.8) * 1000 * surface moyenne.
    # Les cellules Excel vides D/E participent numériquement comme 0.
    if cote is not None and next_cote is not None and surface is not None and next_surface is not None:
        evaporation = (((bac or 0.0) + (pluie or 0.0)) * 0.8) * 1000.0 * ((surface + next_surface) / 2.0)
    else:
        evaporation = None

    source_rest = _abhl_v25_restitutions(code, day, raw)
    day_specials = _abhl_v25_specials(code, day, raw)
    visible_rest = {}
    for visible_code in config.get("restitutions", {}):
        if _abhl_v25_truthy(day_specials.get(_ABHL_V25_REST_BLANK_PREFIX + visible_code)):
            value = None
        elif (_ABHL_V25_REST_OVERRIDE_PREFIX + visible_code) in day_specials:
            value = _abhl_v25_num(day_specials.get(_ABHL_V25_REST_OVERRIDE_PREFIX + visible_code))
        else:
            value = _abhl_v25_restitution_value(code, visible_code, source_rest)
        visible_rest[visible_code] = value

    # Excel : si toutes les restitutions visibles ET la cote suivante sont vides,
    # Total rest. reste vide; sinon SUM(...) retourne 0 ou la somme.
    rest_values = [value for value in visible_rest.values() if value is not None]
    if not rest_values and next_cote is None:
        total_rest = None
    else:
        total_rest = sum(rest_values) if rest_values else 0.0

    specials = {}
    for special_code in config.get("specials", {}):
        specials[special_code] = _abhl_v25_special_value(
            code, special_code, day, raw, visible_rest, next_cote
        )

    transfer = specials.get("TRANSFERT_DAR_KHROFA") if code == "DAR_KHROFA" else 0.0

    # Excel Annonce garde l'apport journalier BRUT, y compris négatif.
    if volume is not None and next_volume is not None:
        apports_raw = (
            (next_volume - volume) * 1_000_000.0
            + (evaporation or 0.0)
            + (total_rest or 0.0)
            - (transfer or 0.0)
        )
    else:
        apports_raw = None

    return {
        "day": day,
        "has_bilan": bool(bilan),
        "cote": cote,
        "volume": volume,
        "surface": surface,
        "bac": bac,
        "pluie": pluie,
        "evaporation": evaporation,
        "restitutions": visible_rest,
        "total_restitutions": total_rest,
        "apports_raw": apports_raw,
        "specials": specials,
    }


def _abhl_v25_month_models(code: str, config: dict, raw: dict) -> list[dict]:
    context = raw["context"]
    result = []
    day = context["month_start"]
    while day < context["next_month_start"]:
        result.append(_abhl_v25_model_row(code, day, config, raw))
        day += timedelta(days=1)
    return result


def fill_monthly_sheet(editor: XlsxTemplateEditor, code: str, config: dict, raw: dict):
    """Remplit une feuille selon les formules générales du classeur agence."""
    context = raw["context"]
    sheet_name = config["sheet_name"]

    editor.set_text(sheet_name, "A4", f"{MONTH_NAMES_FR_UPPER[context['month']]} {context['year']}")

    for offset, day in enumerate(month_dates(context["month_start"])):
        row_number = config["data_start_row"] + offset
        model = _abhl_v25_model_row(code, day, config, raw)

        clear_data_row(editor, sheet_name, row_number, config["last_column"])
        editor.set_date(sheet_name, f"A{row_number}", day)

        editor.set_number(sheet_name, f"B{row_number}", model["cote"])
        editor.set_number(sheet_name, f"C{row_number}", model["volume"])
        editor.set_number(sheet_name, f"D{row_number}", model["bac"])
        editor.set_number(sheet_name, f"E{row_number}", model["pluie"])
        editor.set_number(sheet_name, f"F{row_number}", model["evaporation"])

        for visible_code, column in config.get("restitutions", {}).items():
            # None = non renseigné/non applicable -> cellule vide, 0 explicite -> 0.
            editor.set_number(sheet_name, f"{column}{row_number}", model["restitutions"].get(visible_code))

        editor.set_number(
            sheet_name,
            f"{config['total_restitutions']}{row_number}",
            model["total_restitutions"],
        )
        editor.set_number(sheet_name, f"{config['apports']}{row_number}", model["apports_raw"])

        for special_code, column in config.get("specials", {}).items():
            editor.set_number(sheet_name, f"{column}{row_number}", model["specials"].get(special_code))

    fill_totals(editor, code, config, raw)


def fill_totals(editor: XlsxTemplateEditor, code: str, config: dict, raw: dict):
    models = _abhl_v25_month_models(code, config, raw)
    total_row = config["total_row"]
    sheet_name = config["sheet_name"]

    rainfall_total = sum((m["pluie"] or 0.0) for m in models)
    evaporation_total = sum((m["evaporation"] or 0.0) for m in models)
    editor.set_number(sheet_name, f"E{total_row}", rainfall_total)
    editor.set_number(sheet_name, f"F{total_row}", evaporation_total / 1_000_000.0)

    for visible_code, column in config.get("restitutions", {}).items():
        values = [m["restitutions"].get(visible_code) for m in models]
        total = sum((v or 0.0) for v in values)
        editor.set_number(sheet_name, f"{column}{total_row}", total / 1_000_000.0)

    total_rest = sum((m["total_restitutions"] or 0.0) for m in models)
    editor.set_number(sheet_name, f"{config['total_restitutions']}{total_row}", total_rest / 1_000_000.0)

    # Règle Excel officielle : on somme d'abord TOUS les apports journaliers bruts,
    # négatifs compris, puis seulement le total mensuel est borné à 0.
    raw_total = sum((m["apports_raw"] or 0.0) for m in models)
    editor.set_number(sheet_name, f"{config['apports']}{total_row}", max(0.0, raw_total) / 1_000_000.0)

    for special_code, column in config.get("specials", {}).items():
        if special_code in {"BGE_GARDE_AM", "BGE_GARDE_AV"}:
            editor.clear_cell(sheet_name, f"{column}{total_row}")
            continue
        total = sum((m["specials"].get(special_code) or 0.0) for m in models)
        if special_code == "BGE_GARDE_PLUIE":
            editor.set_number(sheet_name, f"{column}{total_row}", total)
        else:
            editor.set_number(sheet_name, f"{column}{total_row}", total / 1_000_000.0)


def _abhl_v25_crues_volume(code: str, day: date, raw: dict):
    if code not in _ABHL_V25_CRUES_VOLUME_VISIBLE:
        return None
    _cote, volume, _surface = _abhl_v25_volume_surface(code, day, raw)
    if volume is None:
        return None
    decimals = _ABHL_V25_CRUES_VOLUME_DECIMALS.get(code, 3)
    return round(volume, decimals)


def fill_crues_sheet(editor: XlsxTemplateEditor, raw: dict):
    context = raw["context"]
    sheet_name = "ANNONCE DE CRUES"

    # Les mesures sont celles de date_situation, mais les libellés de vacation
    # du classeur agence correspondent à la veille et l'avant-veille.
    editor.set_date(sheet_name, "F4", context["date_interval"])
    editor.set_date(sheet_name, "F5", context["date_interval"] - timedelta(days=1))
    editor.set_text(sheet_name, "T7", f"pluie total mois {MONTH_NAMES_FR_UPPER[context['month']].lower()}")

    for code, row_number in CRUES_BARRAGE_ROWS.items():
        interval = _abhl_v25_bilan(code, context["date_interval"], raw)
        current_cote = _abhl_v25_cote(code, context["date_situation"], raw)

        editor.set_number(sheet_name, f"C{row_number}", _abhl_v25_field(code, context["date_interval"], raw, "pluie_mm"))

        if current_cote is None and code in _ABHL_V25_CRUES_AGITE_IF_MISSING:
            editor.set_text(sheet_name, f"D{row_number}", "ajité")
        else:
            editor.set_number(sheet_name, f"D{row_number}", current_cote)

        editor.set_number(sheet_name, f"F{row_number}", _abhl_v25_crues_volume(code, context["date_situation"], raw))

        monthly_rain = 0.0
        found_rain = False
        day = context["month_start"]
        while day < context["next_month_start"]:
            rain_value = _abhl_v25_field(code, day, raw, "pluie_mm")
            if rain_value is not None:
                monthly_rain += float(rain_value)
                found_rain = True
            day += timedelta(days=1)
        editor.set_number(sheet_name, f"T{row_number}", monthly_rain if found_rain else None)

# === ABHL V25 ANNONCE OFFICIAL ENGINE END ===

# === ABHL V26 ANNONCE FORMULES AGENCE START ===
# Règles générales dérivées du template/formules Excel agence.
# Aucune date, aucun mois et aucune valeur de test n'est codé.

from decimal import Decimal as _ABHL_V26_Decimal

if "_abhl_v26_original_bareme_point" not in globals():
    _abhl_v26_original_bareme_point = _abhl_v25_bareme_point
if "_abhl_v26_original_special_value" not in globals():
    _abhl_v26_original_special_value = _abhl_v25_special_value
if "_abhl_v26_original_fill_totals" not in globals():
    _abhl_v26_original_fill_totals = fill_totals
if "_abhl_v26_original_fill_crues_sheet" not in globals():
    _abhl_v26_original_fill_crues_sheet = fill_crues_sheet
if "_abhl_v26_original_generate_annonce_excel" not in globals():
    _abhl_v26_original_generate_annonce_excel = generate_annonce_excel

_ABHL_V26_RULES_READY = False
_ABHL_V26_EXACT_BAREMES = {}
_ABHL_V26_TOTAL_GUARDS = {}
_ABHL_V26_CRUES_RAIN_VISIBLE = {}
_ABHL_V26_RANGE_RE = re.compile(
    r"'Baréms des barrages'!\$([A-Z]+)\$(\d+):\$([A-Z]+)\$(\d+)",
    re.IGNORECASE,
)
_ABHL_V26_COUNTBLANK_RE = re.compile(
    r"COUNTBLANK\(\$([A-Z]+)\$(\d+):\$([A-Z]+)\$(\d+)\)\s*>\s*(\d+)",
    re.IGNORECASE,
)


def _abhl_v26_cell_map(editor, sheet_name):
    cache = getattr(editor, "_abhl_v26_cell_maps", None)
    if cache is None:
        cache = {}
        setattr(editor, "_abhl_v26_cell_maps", cache)
    if sheet_name in cache:
        return cache[sheet_name]
    root = editor.require_sheet(sheet_name)
    mapping = {}
    for cell in root.iter(qn("c")):
        ref = (cell.attrib.get("r") or "").upper()
        if ref:
            mapping[ref] = cell
    cache[sheet_name] = mapping
    return mapping


def _abhl_v26_cell(editor, sheet_name, ref):
    return _abhl_v26_cell_map(editor, sheet_name).get(str(ref).upper())


def _abhl_v26_formula(editor, sheet_name, ref):
    cell = _abhl_v26_cell(editor, sheet_name, ref)
    if cell is None:
        return None
    node = cell.find(qn("f"))
    return None if node is None else (node.text or "")


def _abhl_v26_cached_decimal(editor, sheet_name, ref):
    cell = _abhl_v26_cell(editor, sheet_name, ref)
    if cell is None:
        return None
    value_node = cell.find(qn("v"))
    if value_node is None or value_node.text in (None, ""):
        return None
    try:
        return _ABHL_V26_Decimal(value_node.text)
    except Exception:
        return None


def _abhl_v26_cell_has_payload(editor, sheet_name, ref):
    cell = _abhl_v26_cell(editor, sheet_name, ref)
    if cell is None:
        return False
    return any(cell.find(qn(tag)) is not None for tag in ("f", "v", "is"))


def _abhl_v26_col_index(col):
    value = 0
    for ch in str(col).upper():
        value = value * 26 + (ord(ch) - 64)
    return value


def _abhl_v26_col_name(index):
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _abhl_v26_read_range(editor, col, row_start, row_end):
    return [
        _abhl_v26_cached_decimal(editor, "Baréms des barrages", f"{col}{row}")
        for row in range(int(row_start), int(row_end) + 1)
    ]


def _abhl_v26_build_exact_bareme(editor, code, config):
    sheet_name = config["sheet_name"]
    first_row = int(config["data_start_row"])
    volume_formula = _abhl_v26_formula(editor, sheet_name, f"C{first_row}") or ""
    evap_formula = _abhl_v26_formula(editor, sheet_name, f"F{first_row}") or ""

    volume_ranges = _ABHL_V26_RANGE_RE.findall(volume_formula)
    evap_ranges = _ABHL_V26_RANGE_RE.findall(evap_formula)
    if len(volume_ranges) < 2 or len(evap_ranges) < 2:
        return None

    cote_range = volume_ranges[0]
    volume_range = volume_ranges[1]
    evap_cote_range = evap_ranges[0]
    surface_range = evap_ranges[1]

    if cote_range != evap_cote_range:
        return None

    cote_col, cote_start, cote_end_col, cote_end = cote_range
    vol_col, vol_start, vol_end_col, vol_end = volume_range
    surf_col, surf_start, surf_end_col, surf_end = surface_range
    if cote_col != cote_end_col or vol_col != vol_end_col or surf_col != surf_end_col:
        return None

    cotes = _abhl_v26_read_range(editor, cote_col, cote_start, cote_end)
    volumes = _abhl_v26_read_range(editor, vol_col, vol_start, vol_end)
    surfaces = _abhl_v26_read_range(editor, surf_col, surf_start, surf_end)
    count = min(len(cotes), len(volumes), len(surfaces))
    if count <= 0:
        return None

    # SUMIF : s'il existe plusieurs lignes avec la même cote, Excel les somme.
    exact = {}
    for idx in range(count):
        cote = cotes[idx]
        if cote is None:
            continue
        entry = exact.setdefault(
            cote,
            {
                "cote_ngm": cote,
                "volume_mm3": _ABHL_V26_Decimal("0"),
                "surface_km2": _ABHL_V26_Decimal("0"),
            },
        )
        if volumes[idx] is not None:
            entry["volume_mm3"] += volumes[idx]
        if surfaces[idx] is not None:
            entry["surface_km2"] += surfaces[idx]
    return exact or None


def _abhl_v26_parse_total_guards(editor, code, config):
    sheet = config["sheet_name"]
    total_row = int(config["total_row"])
    guards = []
    for col_idx in range(_abhl_v26_col_index("E"), _abhl_v26_col_index(config["last_column"]) + 1):
        col = _abhl_v26_col_name(col_idx)
        ref = f"{col}{total_row}"
        formula = _abhl_v26_formula(editor, sheet, ref) or ""
        match = _ABHL_V26_COUNTBLANK_RE.search(formula)
        if not match:
            continue
        guards.append(
            {
                "cell": ref,
                "start_col": match.group(1).upper(),
                "start_row": int(match.group(2)),
                "end_col": match.group(3).upper(),
                "end_row": int(match.group(4)),
                "threshold": int(match.group(5)),
            }
        )
    return guards


def _abhl_v26_ensure_rules():
    global _ABHL_V26_RULES_READY
    if _ABHL_V26_RULES_READY:
        return

    template_editor = XlsxTemplateEditor(resolve_template_path())

    for code, config in SHEET_CONFIGS.items():
        try:
            exact = _abhl_v26_build_exact_bareme(template_editor, code, config)
            if exact:
                _ABHL_V26_EXACT_BAREMES[code] = exact
        except Exception:
            # Barrage dynamique/structure future : V25 reste le fallback.
            pass
        try:
            _ABHL_V26_TOTAL_GUARDS[code] = _abhl_v26_parse_total_guards(
                template_editor, code, config
            )
        except Exception:
            _ABHL_V26_TOTAL_GUARDS[code] = []

    for code, row_number in CRUES_BARRAGE_ROWS.items():
        _ABHL_V26_CRUES_RAIN_VISIBLE[code] = _abhl_v26_cell_has_payload(
            template_editor, "ANNONCE DE CRUES", f"T{row_number}"
        )

    _ABHL_V26_RULES_READY = True


def _abhl_v25_bareme_point(code: str, cote, raw: dict):
    _abhl_v26_ensure_rules()
    exact = _ABHL_V26_EXACT_BAREMES.get(code)
    numeric_cote = _abhl_v25_num(cote)
    if exact is None or numeric_cote is None:
        return _abhl_v26_original_bareme_point(code, cote, raw)

    key = _ABHL_V26_Decimal(str(numeric_cote))
    entry = exact.get(key)
    if entry is None:
        # Tolérance uniquement contre le bruit de représentation, JAMAIS une interpolation.
        tolerance = _ABHL_V26_Decimal("0.0000005")
        for exact_key, candidate in exact.items():
            if abs(exact_key - key) <= tolerance:
                entry = candidate
                break

    # SUMIF Excel sur une cote non vide mais introuvable renvoie 0.
    if entry is None:
        return {"cote_ngm": numeric_cote, "volume_mm3": 0.0, "surface_km2": 0.0}

    return {
        "cote_ngm": float(entry["cote_ngm"]),
        "volume_mm3": float(entry["volume_mm3"]),
        "surface_km2": float(entry["surface_km2"]),
    }


def _abhl_v25_special_value(code: str, special_code: str, day: date, raw: dict, visible_rest: dict, next_cote):
    # Toutes les autres règles restent celles de V25.
    if code != "DAR_KHROFA" or special_code != "UTILISATION_IRRIGATION":
        return _abhl_v26_original_special_value(
            code, special_code, day, raw, visible_rest, next_cote
        )

    # Formule agence exacte :
    # IF(OR(ISBLANK(PriseAgricole),ISBLANK(AEPITanger)),"",PriseAgricole-AEPITanger)
    prise = visible_rest.get("PRISE_AGRICOLE")
    aepi_tanger = _abhl_v26_original_special_value(
        code, "UTILISATION_AEPI_TANGER", day, raw, visible_rest, next_cote
    )
    if prise is None or aepi_tanger is None:
        return None
    return float(prise) - float(aepi_tanger)


def _abhl_v26_cell_is_blank(editor, sheet_name, ref):
    cell = _abhl_v26_cell(editor, sheet_name, ref)
    if cell is None:
        return True
    value_node = cell.find(qn("v"))
    inline = cell.find(qn("is"))
    formula = cell.find(qn("f"))
    # Après V25 les cellules quotidiennes sont des valeurs, pas des formules.
    if value_node is not None and (value_node.text or "") != "":
        return False
    if inline is not None:
        texts = [node.text or "" for node in inline.iter(qn("t"))]
        return "".join(texts) == ""
    if formula is not None:
        cached = cell.find(qn("v"))
        return cached is None or (cached.text or "") == ""
    return True


def _abhl_v26_count_blank(editor, sheet_name, guard):
    total = 0
    for row in range(guard["start_row"], guard["end_row"] + 1):
        for col_idx in range(
            _abhl_v26_col_index(guard["start_col"]),
            _abhl_v26_col_index(guard["end_col"]) + 1,
        ):
            ref = f"{_abhl_v26_col_name(col_idx)}{row}"
            if _abhl_v26_cell_is_blank(editor, sheet_name, ref):
                total += 1
    return total


def fill_totals(editor: XlsxTemplateEditor, code: str, config: dict, raw: dict):
    _abhl_v26_ensure_rules()
    result = _abhl_v26_original_fill_totals(editor, code, config, raw)
    sheet_name = config["sheet_name"]
    for guard in _ABHL_V26_TOTAL_GUARDS.get(code, []):
        if _abhl_v26_count_blank(editor, sheet_name, guard) > guard["threshold"]:
            editor.clear_cell(sheet_name, guard["cell"])
    return result


def fill_crues_sheet(editor: XlsxTemplateEditor, raw: dict):
    _abhl_v26_ensure_rules()
    result = _abhl_v26_original_fill_crues_sheet(editor, raw)
    for code, row_number in CRUES_BARRAGE_ROWS.items():
        if not _ABHL_V26_CRUES_RAIN_VISIBLE.get(code, False):
            editor.clear_cell("ANNONCE DE CRUES", f"T{row_number}")
    return result


def generate_annonce_excel(db: Session, date_situation: date) -> Path:
    # Charge une seule fois les règles du template AVANT toute génération.
    _abhl_v26_ensure_rules()
    return _abhl_v26_original_generate_annonce_excel(db, date_situation)

# === ABHL V26 ANNONCE FORMULES AGENCE END ===

# === ABHL BAREMES V27 ANNONCE VERSIONED POINTS START ===
_abhl_v27_annonce_volume_surface_legacy = _abhl_v25_volume_surface

def _abhl_v25_volume_surface(code: str, day: date, raw: dict):
    version = (raw.get("_abhl_v27_bareme_versions_by_date") or {}).get((code, day.isoformat()))
    if not version or version.get("calculation_source") != "DATABASE_VERSIONED":
        # Barèmes 2023 existants : garder EXACTEMENT la précision/template validée en V26.
        return _abhl_v27_annonce_volume_surface_legacy(code, day, raw)
    cote = _abhl_v25_cote(code, day, raw)
    if cote is None:
        return None, None, None
    points = (raw.get("_abhl_v27_bareme_points_by_version") or {}).get(int(version["id"]), [])
    from decimal import Decimal as _D
    target = _D(str(cote))
    tolerance = _D("0.0000005")
    for p in points:
        pc = _D(str(p.get("cote_ngm")))
        if abs(pc-target) <= tolerance:
            return cote, _abhl_v25_num(p.get("volume_mm3")), _abhl_v25_num(p.get("surface_km2"))
    # Reproduit SUMIF exact : cote non trouvée => 0, aucune interpolation.
    return cote, 0.0, 0.0
# === ABHL BAREMES V27 ANNONCE VERSIONED POINTS END ===
