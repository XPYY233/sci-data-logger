from pathlib import Path

from sci_data_logger.adapters.generic_csv import GenericCSVAdapter


def test_two_column_numeric_csv_is_treated_as_curve_data(tmp_path: Path) -> None:
    csv_path = tmp_path / "spectrum.csv"
    csv_path.write_text(
        "angle,intensity\n10,100\n10.1,105\n10.2,99\n10.3,110\n",
        encoding="utf-8",
    )

    result = GenericCSVAdapter().parse(csv_path)

    assert result.raw_parameters["columns"] == ["angle", "intensity"]
    assert result.raw_parameters["row_count"] == 4
    assert result.raw_parameters["data_preview"][0] == ["10", "100"]
    assert "10" not in result.raw_parameters
    assert result.warnings


def test_two_column_non_numeric_csv_stays_key_value_metadata(tmp_path: Path) -> None:
    csv_path = tmp_path / "metadata.csv"
    csv_path.write_text("operator,Ada\nsample,S-1\nmethod,XRD\n", encoding="utf-8")

    result = GenericCSVAdapter().parse(csv_path)

    assert result.raw_parameters == {
        "operator": "Ada",
        "sample": "S-1",
        "method": "XRD",
    }
    assert result.warnings == []
