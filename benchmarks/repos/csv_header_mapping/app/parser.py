def parse_record(header_line: str, row_line: str) -> dict[str, str]:
    headers = header_line.split(",")
    values = row_line.split(",")
    return dict(zip(sorted(headers), values))
