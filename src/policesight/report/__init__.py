"""policesight.report：周研判报告（HTML 内联 SVG + DOCX 表格；python-docx）。"""

from .report import build_weekly, render_docx, render_html

__all__ = ["build_weekly", "render_docx", "render_html"]
