"""Plain-text and Markdown tables for the dashboard."""


def render_table(headers: list[str], rows: list[list]) -> str:
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    lines = [" | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows:
        lines.append(" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(lines)


def render_totals(headers: list[str], rows: list[list], label: str = "Total") -> str:
    totals = [label]
    for i in range(1, len(headers)):
        values = [row[i] for row in rows]
        if values and all(isinstance(v, (int, float)) for v in values):
            totals.append(sum(values))
        else:
            totals.append("")
    all_rows = [*rows, totals]
    widths = [len(str(h)) for h in headers]
    for row in all_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    lines = [" | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows:
        lines.append(" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    lines.append("=+=".join("=" * w for w in widths))
    lines.append(" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(totals)).rstrip())
    return "\n".join(lines)


def render_markdown(headers: list[str], rows: list[list]) -> str:
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    widths = [max(w, 3) for w in widths]
    lines = ["| " + " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)) + " |"]
    lines.append("| " + " | ".join("-" * w for w in widths) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)) + " |")
    return "\n".join(lines)
