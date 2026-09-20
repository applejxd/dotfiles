from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent
FILES = ROOT / "files"
NAVY = RGBColor(15, 32, 58)
BLUE = RGBColor(26, 115, 232)
PALE = RGBColor(235, 241, 250)
MUTED = RGBColor(83, 101, 127)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    suffix = "Bold" if bold else ""
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{('-' + suffix) if suffix else ''}.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(path, size)
    raise FileNotFoundError("A DejaVu font is required to build fixtures.")


def add_text(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    size: float,
    color: RGBColor = NAVY,
    bold: bool = False,
    name: str | None = None,
):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        shape.name = name
    shape.text_frame.clear()
    shape.text_frame.margin_left = 0
    shape.text_frame.margin_right = 0
    paragraph = shape.text_frame.paragraphs[0]
    run = paragraph.add_run()
    run.text = text
    run.font.name = "DejaVu Sans"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return shape


def add_header(slide, title: str, section: str) -> None:
    add_text(slide, section.upper(), 0.78, 0.35, 2.7, 0.3, 10, BLUE, True, "Section")
    add_text(slide, title, 0.78, 0.72, 11.6, 0.68, 28, NAVY, True, "Title")
    line = slide.shapes.add_shape(1, Inches(0.78), Inches(1.48), Inches(11.75), Inches(0.03))
    line.name = "Header Rule"
    line.fill.solid()
    line.fill.fore_color.rgb = BLUE
    line.line.fill.background()


def style_panel(shape, fill: RGBColor = PALE) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = RGBColor(207, 218, 233)


def build_template() -> None:
    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    blank = presentation.slide_layouts[6]

    slide = presentation.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = NAVY
    add_text(
        slide,
        "NORTHSTAR / ENGINEERING",
        0.82,
        0.58,
        4.2,
        0.3,
        10,
        RGBColor(139, 190, 255),
        True,
        "Eyebrow",
    )
    add_text(slide, "{{TITLE}}", 0.82, 1.52, 7.9, 1.55, 36, RGBColor(255, 255, 255), True, "Title")
    add_text(
        slide, "{{SUBTITLE}}", 0.86, 3.28, 6.8, 0.8, 17, RGBColor(204, 216, 235), False, "Subtitle"
    )
    panel = slide.shapes.add_shape(1, Inches(9.2), Inches(0), Inches(4.133), Inches(7.5))
    panel.name = "Cover Accent"
    panel.fill.solid()
    panel.fill.fore_color.rgb = BLUE
    panel.line.fill.background()
    add_text(slide, "01", 10.15, 5.45, 2.2, 0.9, 42, RGBColor(255, 255, 255), True, "Slide Number")

    slide = presentation.slides.add_slide(blank)
    add_header(slide, "{{TITLE}}", "CONTEXT")
    panel = slide.shapes.add_shape(5, Inches(0.8), Inches(1.83), Inches(5.0), Inches(4.75))
    panel.name = "Narrative Panel"
    style_panel(panel)
    add_text(slide, "{{LEFT_HEADLINE}}", 1.15, 2.2, 4.25, 0.65, 23, NAVY, True, "Left Headline")
    add_text(slide, "{{LEFT_BODY}}", 1.15, 3.05, 4.1, 2.6, 17, MUTED, False, "Left Body")
    chart = slide.shapes.add_shape(5, Inches(6.18), Inches(1.83), Inches(6.35), Inches(4.75))
    chart.name = "Visual Panel"
    style_panel(chart, RGBColor(248, 250, 253))
    add_text(slide, "{{VISUAL}}", 7.25, 3.7, 4.1, 0.5, 16, MUTED, True, "Visual Placeholder")

    slide = presentation.slides.add_slide(blank)
    add_header(slide, "{{TITLE}}", "COMPARISON")
    for i, x in enumerate((0.8, 6.78), start=1):
        panel = slide.shapes.add_shape(5, Inches(x), Inches(1.83), Inches(5.75), Inches(4.78))
        panel.name = f"Comparison Panel {i}"
        style_panel(panel, RGBColor(248, 250, 253) if i == 1 else PALE)
        add_text(
            slide, f"{{{{OPTION_{i}}}}}", x + 0.4, 2.2, 4.9, 0.5, 20, NAVY, True, f"Option {i}"
        )
        add_text(
            slide, f"{{{{DETAIL_{i}}}}}", x + 0.4, 3.05, 4.85, 2.75, 16, MUTED, False, f"Detail {i}"
        )

    slide = presentation.slides.add_slide(blank)
    add_header(slide, "{{TITLE}}", "EVIDENCE")
    chart = slide.shapes.add_shape(5, Inches(0.8), Inches(1.83), Inches(8.2), Inches(4.78))
    chart.name = "Chart Panel"
    style_panel(chart, RGBColor(248, 250, 253))
    add_text(slide, "{{CHART}}", 3.65, 3.65, 2.5, 0.5, 16, MUTED, True, "Chart Placeholder")
    kpi = slide.shapes.add_shape(5, Inches(9.3), Inches(1.83), Inches(3.23), Inches(4.78))
    kpi.name = "KPI Panel"
    style_panel(kpi, NAVY)
    add_text(slide, "{{KPI}}", 9.75, 2.5, 2.35, 1.0, 36, RGBColor(255, 255, 255), True, "KPI")
    add_text(
        slide,
        "{{KPI_LABEL}}",
        9.75,
        3.65,
        2.25,
        1.2,
        15,
        RGBColor(204, 216, 235),
        False,
        "KPI Label",
    )

    slide = presentation.slides.add_slide(blank)
    add_header(slide, "{{TITLE}}", "PLAN")
    y = 2.25
    for index, label in enumerate(("WEEK 1", "WEEK 2", "WEEK 3", "WEEK 4"), start=1):
        x = 0.9 + (index - 1) * 3.05
        circle = slide.shapes.add_shape(9, Inches(x), Inches(y), Inches(0.62), Inches(0.62))
        circle.name = f"Step Marker {index}"
        circle.fill.solid()
        circle.fill.fore_color.rgb = BLUE
        circle.line.fill.background()
        number = add_text(
            slide,
            str(index),
            x,
            y + 0.07,
            0.62,
            0.35,
            16,
            RGBColor(255, 255, 255),
            True,
            f"Step Number {index}",
        )
        number.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        add_text(slide, label, x, y + 0.95, 2.4, 0.35, 11, BLUE, True, f"Step Label {index}")
        add_text(
            slide, f"{{{{STEP_{index}}}}}", x, y + 1.35, 2.35, 1.35, 16, NAVY, True, f"Step {index}"
        )
        if index < 4:
            connector = slide.shapes.add_shape(
                1, Inches(x + 0.65), Inches(y + 0.28), Inches(2.37), Inches(0.05)
            )
            connector.name = f"Connector {index}"
            connector.fill.solid()
            connector.fill.fore_color.rgb = RGBColor(180, 197, 220)
            connector.line.fill.background()

    slide = presentation.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = BLUE
    add_text(
        slide, "{{DECISION}}", 0.92, 1.42, 10.7, 1.45, 34, RGBColor(255, 255, 255), True, "Decision"
    )
    add_text(
        slide,
        "{{NEXT_ACTION}}",
        0.96,
        3.25,
        7.6,
        0.85,
        18,
        RGBColor(229, 239, 255),
        False,
        "Next Action",
    )
    add_text(
        slide,
        "NORTHSTAR / ENGINEERING",
        0.96,
        6.55,
        4.2,
        0.3,
        10,
        RGBColor(210, 229, 255),
        True,
        "Footer",
    )

    presentation.core_properties.title = "Northstar engineering template"
    presentation.core_properties.subject = "Evaluation fixture"
    presentation.save(FILES / "corporate-template.pptx")


def dashboard_image(path: Path, size: tuple[int, int], variant: str) -> None:
    image = Image.new("RGB", size, "#F3F6FA")
    draw = ImageDraw.Draw(image)
    width, height = size
    sidebar = round(width * 0.15)
    draw.rectangle((0, 0, sidebar, height), fill="#10213A")
    draw.text(
        (sidebar * 0.18, height * 0.06),
        "NORTHSTAR",
        font=font(max(20, width // 55), True),
        fill="#FFFFFF",
    )
    for index, item in enumerate(("Overview", "Reviews", "Risks", "Teams", "Settings")):
        color = "#8BBEFF" if index == 1 else "#A8B6CA"
        draw.text(
            (sidebar * 0.18, height * (0.18 + index * 0.09)),
            item,
            font=font(max(14, width // 80)),
            fill=color,
        )
    draw.text(
        (sidebar + width * 0.045, height * 0.055),
        variant,
        font=font(max(25, width // 42), True),
        fill="#10213A",
    )
    draw.text(
        (sidebar + width * 0.045, height * 0.115),
        "Last 30 days",
        font=font(max(14, width // 85)),
        fill="#63738B",
    )

    card_gap = width * 0.025
    card_w = (width - sidebar - width * 0.12 - 2 * card_gap) / 3
    for index, (metric, label, accent) in enumerate(
        (
            ("2.6h", "Median first response", "#1A73E8"),
            ("31%", "Less review wait", "#00A77A"),
            ("94%", "Policy coverage", "#7C4DFF"),
        )
    ):
        x = sidebar + width * 0.045 + index * (card_w + card_gap)
        y = height * 0.18
        draw.rounded_rectangle(
            (x, y, x + card_w, y + height * 0.18),
            radius=18,
            fill="#FFFFFF",
            outline="#D9E2EF",
            width=2,
        )
        draw.text((x + 24, y + 22), metric, font=font(max(28, width // 38), True), fill=accent)
        draw.text(
            (x + 24, y + height * 0.12), label, font=font(max(13, width // 90)), fill="#63738B"
        )

    chart_left = sidebar + width * 0.045
    chart_top = height * 0.43
    chart_right = width * 0.71
    chart_bottom = height * 0.88
    draw.rounded_rectangle(
        (chart_left, chart_top, chart_right, chart_bottom),
        radius=18,
        fill="#FFFFFF",
        outline="#D9E2EF",
        width=2,
    )
    draw.text(
        (chart_left + 24, chart_top + 20),
        "Review cycle time",
        font=font(max(16, width // 70), True),
        fill="#10213A",
    )
    points = [0.78, 0.71, 0.67, 0.56, 0.49, 0.43, 0.35]
    coords = []
    for index, value in enumerate(points):
        px = chart_left + 50 + index * (chart_right - chart_left - 100) / (len(points) - 1)
        py = chart_top + 80 + value * (chart_bottom - chart_top - 130)
        coords.append((px, py))
    draw.line(coords, fill="#1A73E8", width=max(4, width // 300), joint="curve")
    for point in coords:
        draw.ellipse((point[0] - 7, point[1] - 7, point[0] + 7, point[1] + 7), fill="#1A73E8")
    panel_left = width * 0.74
    draw.rounded_rectangle(
        (panel_left, chart_top, width * 0.955, chart_bottom), radius=18, fill="#10213A"
    )
    draw.text(
        (panel_left + 25, chart_top + 25),
        "Top finding",
        font=font(max(16, width // 75), True),
        fill="#8BBEFF",
    )
    draw.text(
        (panel_left + 25, chart_top + 75),
        "Routine policy feedback\narrives before a human\nopens the pull request.",
        font=font(max(18, width // 62), True),
        fill="#FFFFFF",
        spacing=10,
    )
    image.save(path, quality=95)


def build_screenshots() -> None:
    dashboard_image(FILES / "dashboard.png", (1800, 1125), "Review operations")
    dashboard_image(FILES / "detail-view.png", (1600, 1000), "Pull request detail")
    dashboard_image(FILES / "mobile-view.png", (900, 1600), "Mobile review queue")


def build_csv() -> None:
    rows = [
        ["method", "accuracy_mean", "accuracy_std", "latency_ms", "trials", "variant"],
        ["Baseline CNN", "82.4", "0.7", "18.2", "5", "main"],
        ["Augmented CNN", "85.1", "0.6", "19.8", "5", "main"],
        ["Proposed", "89.3", "0.4", "21.1", "5", "main"],
        ["Proposed", "86.0", "0.5", "21.0", "without attention"],
        ["Proposed", "87.2", "0.5", "19.6", "without multiscale"],
        ["Proposed", "88.1", "0.4", "20.4", "without calibration"],
    ]
    with (FILES / "experiment-results.csv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


def main() -> None:
    FILES.mkdir(parents=True, exist_ok=True)
    build_template()
    build_screenshots()
    build_csv()
    print(f"Built fixtures in {FILES}")


if __name__ == "__main__":
    main()
