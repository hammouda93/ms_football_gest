"""Small dependency-free reader for SportsBase Players XLSX exports."""

from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _column_index(reference):
    letters = "".join(character for character in reference if character.isalpha())
    value = 0
    for letter in letters.upper():
        value = value * 26 + ord(letter) - ord("A") + 1
    return max(0, value - 1)


def _cell_text(cell, shared_strings):
    kind = cell.attrib.get("t", "")
    if kind == "inlineStr":
        return "".join(
            node.text or "" for node in cell.findall(f".//{{{MAIN_NS}}}t")
        )
    value_node = cell.find(f"{{{MAIN_NS}}}v")
    if value_node is None:
        return ""
    raw = value_node.text or ""
    if kind == "s":
        try:
            return shared_strings[int(raw)]
        except (IndexError, TypeError, ValueError):
            return ""
    if kind in {"str", "e"}:
        return raw
    if kind == "b":
        return raw == "1"
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return raw
    return int(number) if number.is_integer() else number


def _shared_strings(workbook):
    try:
        root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.findall(f".//{{{MAIN_NS}}}t"))
        for item in root.findall(f"{{{MAIN_NS}}}si")
    ]


def _first_sheet_path(workbook):
    root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
    sheet = root.find(f".//{{{MAIN_NS}}}sheet")
    if sheet is None:
        raise ValueError("Le classeur SportsBase ne contient aucune feuille.")
    relationship_id = sheet.attrib.get(f"{{{REL_NS}}}id")
    relationships = ElementTree.fromstring(
        workbook.read("xl/_rels/workbook.xml.rels")
    )
    for relationship in relationships.findall(
        f"{{{PACKAGE_REL_NS}}}Relationship"
    ):
        if relationship.attrib.get("Id") != relationship_id:
            continue
        target = relationship.attrib.get("Target", "")
        if target.startswith("/"):
            return target.lstrip("/")
        return "xl/" + target.lstrip("/")
    raise ValueError("La première feuille SportsBase est inaccessible.")


def read_players_statistics_xlsx(path):
    """Return JSON-safe headers and player rows from a SportsBase workbook."""
    path = Path(path)
    try:
        with ZipFile(path) as workbook:
            shared_strings = _shared_strings(workbook)
            sheet_path = _first_sheet_path(workbook)
            root = ElementTree.fromstring(workbook.read(sheet_path))
    except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("Le fichier reçu n’est pas un classeur XLSX lisible.") from exc

    matrix = []
    for row in root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
        values = []
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            index = _column_index(cell.attrib.get("r", ""))
            if len(values) <= index:
                values.extend([""] * (index + 1 - len(values)))
            values[index] = _cell_text(cell, shared_strings)
        matrix.append(values)

    if not matrix:
        raise ValueError("Le classeur SportsBase ne contient aucune statistique.")
    headers = [str(value or "").strip() for value in matrix[0]]
    rows = []
    for values in matrix[1:]:
        padded = values + [""] * max(0, len(headers) - len(values))
        row = {
            header: padded[index]
            for index, header in enumerate(headers)
            if header
        }
        if str(row.get("Player") or "").strip():
            rows.append(row)
    return {"headers": headers, "rows": rows}
