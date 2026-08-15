from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _money(value: float | None) -> str:
    return f"{value or 0:,.2f}"


templates.env.filters["money"] = _money
