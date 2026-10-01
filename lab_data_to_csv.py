"""Convert tab-separated lab exports to CSV, including extensionless files.

GOOGLE COLAB: Paste this entire file into one code cell and run it. Click
"Choose Files", select your export(s), and each CSV download starts automatically.
No package installation is needed.

Expected format: optional "Name: value" metadata lines, a tab-separated header,
then tab-separated measurements. Blank lines are allowed. Column names, number
of columns, metadata fields, and number of rows are discovered from the file.
By default metadata becomes extra columns repeated on each measurement row.

Conversion streams one row at a time and preserves numeric text (e.g. 0.00).
There is no fixed row count or file-size limit in the converter, but available
disk space still matters. Colab's upload helper holds uploads in RAM, and the
browser also needs memory for downloads, so arbitrarily large uploads cannot
be guaranteed. For data already on disk, call convert_to_csv(path) directly.

Colab API reference:
https://github.com/googlecolab/colabtools/blob/main/google/colab/files.py
"""

import codecs
import csv
import os
from pathlib import Path
import tempfile


# Optional settings; the supplied lab file works with these defaults.
INCLUDE_METADATA = True  # False exports only the measurement columns.
INPUT_ENCODING = None  # Auto: UTF BOM detection, otherwise UTF-8. Or e.g. "cp1252".


def detect_encoding(path):
    """Detect Unicode byte-order marks without reading the whole file."""
    with Path(path).open("rb") as source:
        prefix = source.read(4)
    if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"
    if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    return "utf-8-sig"  # Also reads ASCII and ordinary UTF-8 without a BOM.


def is_blank_row(row):
    """Skip empty physical lines, but preserve tab-separated empty cells."""
    return not row or (len(row) == 1 and not row[0].strip())


def read_header(reader):
    """Consume metadata and the header; leave the reader at the data rows."""
    metadata = []
    for row in reader:
        if is_blank_row(row):
            continue
        if len(row) == 1 and ":" in row[0]:
            key, _, value = row[0].partition(":")
            if not key.strip():
                raise ValueError(f"Line {reader.line_num}: metadata name is empty.")
            metadata.append((key.strip(), value.strip()))
            continue
        headers = [cell.strip() for cell in row]
        if any(not name for name in headers):
            raise ValueError(f"Line {reader.line_num}: a column name is empty.")
        if len(set(headers)) != len(headers):
            raise ValueError(f"Line {reader.line_num}: duplicate column names.")
        return headers, metadata
    raise ValueError("The file is empty or contains metadata without a table header.")


def metadata_columns(headers, metadata):
    """Keep every metadata field, giving conflicting names a unique suffix."""
    used = set(headers)
    names, values = [], []
    for key, value in metadata:
        name = key
        suffix = 2
        while name in used:
            name = f"{key} ({suffix})"
            suffix += 1
        used.add(name)
        names.append(name)
        values.append(value)
    return names, values


def convert_to_csv(input_path, output_path=None, *, include_metadata=True, encoding=None):
    """Stream one lab export to CSV and return (output Path, measurement count).

    Reusable outside Colab. Example:
        output, count = convert_to_csv("Lab1 Part 1a", "Lab1 Part 1a.csv")

    Existing outputs are protected. Invalid rows produce an error with a line
    number instead of being dropped or silently shifted into the wrong columns.
    The final CSV is only created after the whole input validates successfully.
    """
    source_path = Path(input_path).expanduser().resolve()
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else source_path.with_suffix(".csv")
    )
    if source_path == destination:
        raise ValueError("Choose an output path different from the input path.")
    if destination.exists():
        raise FileExistsError(f"Output already exists: {destination}")

    temporary_path = None
    reader = None
    try:
        with source_path.open(
            "r", encoding=encoding or detect_encoding(source_path), newline=""
        ) as source:
            reader = csv.reader(source, delimiter="\t", strict=True)
            headers, metadata = read_header(reader)
            extra_headers, extra_values = metadata_columns(
                headers, metadata if include_metadata else []
            )
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8-sig", newline="", delete=False,
                dir=destination.parent, prefix=".lab_csv_", suffix=".tmp"
            ) as target:
                temporary_path = Path(target.name)
                writer = csv.writer(target)
                writer.writerow(headers + extra_headers)
                row_count = 0
                for row in reader:
                    if is_blank_row(row):
                        continue
                    if len(row) != len(headers):
                        raise ValueError(
                            f"Line {reader.line_num}: expected {len(headers)} "
                            f"tab-separated fields, found {len(row)}. "
                            "Check for missing or extra tabs."
                        )
                    writer.writerow(row + extra_values)
                    row_count += 1
                if row_count == 0:
                    raise ValueError("The table has a header but no measurement rows.")
        # Reserve the name exclusively, then publish the finished file. This also
        # works on writable filesystems that do not support hard links.
        with destination.open("xb"):
            pass
        try:
            os.replace(temporary_path, destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return destination, row_count
    except UnicodeError as error:
        raise ValueError(
            "Could not decode the file. Set INPUT_ENCODING (or the encoding "
            "argument) to its text encoding, for example 'cp1252'."
        ) from error
    except csv.Error as error:
        line_number = reader.line_num if reader is not None else "unknown"
        raise ValueError(f"Invalid tab-separated data near line {line_number}: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def unused_csv_path(folder, input_name):
    """Avoid collisions when uploaded files have the same stem."""
    stem = Path(input_name).stem
    candidate = Path(folder) / f"{stem}.csv"
    suffix = 2
    while candidate.exists():
        candidate = Path(folder) / f"{stem} ({suffix}).csv"
        suffix += 1
    return candidate


def run_colab():
    """Show Colab's file picker, convert each selection, and start downloads."""
    try:
        from google.colab import files
    except ImportError as error:
        raise RuntimeError(
            "Paste this script into a Google Colab code cell for upload/download "
            "buttons. Outside Colab, import and call convert_to_csv(path)."
        ) from error

    # Keep output files available after this function returns: downloads are async.
    work_dir = Path(tempfile.mkdtemp(prefix="lab_csv_"))
    output_dir = work_dir / "csv"
    output_dir.mkdir()
    print("Choose your tab-separated lab data file(s); an extension is not required.")
    uploaded = files.upload(target_dir=str(work_dir / "uploads"))
    input_paths = list(uploaded)
    uploaded.clear()  # files.upload has already saved these bytes to disk.
    if not input_paths:
        print("No files selected.")
        return []

    completed = []
    for input_path in input_paths:
        name = Path(input_path).name
        output_path = unused_csv_path(output_dir, name)
        try:
            output_path, count = convert_to_csv(
                input_path, output_path,
                include_metadata=INCLUDE_METADATA, encoding=INPUT_ENCODING
            )
        except (OSError, ValueError) as error:
            print(f"Could not convert {name}: {error}")
            continue
        completed.append(output_path)
        print(f"Converted {name}: {count:,} rows. Starting {output_path.name} download.")
        try:
            files.download(str(output_path))
        except Exception as error:
            print(f"Automatic download failed: {error}. Your CSV is saved at {output_path}")
    return completed


if __name__ == "__main__":
    run_colab()
