"""FastAPI 看板服务（离线）：静态前端 + 只读数据接口。默认仅监听 127.0.0.1。"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__

STATIC_DIR = Path(__file__).parent / "static"


def create_app(data_dir: Path | str, *, default_limit: int = 1000) -> FastAPI:
    data_dir = Path(data_dir)
    payload_dir = data_dir / "web" / "data"
    cache: dict[str, object] = {"rows": None, "days": {}, "start": None}

    app = FastAPI(title="PoliceSight · 警情时空研判看板", version=__version__)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # 看板数据（构建产物；目录不存在时先建空目录，访问时给出 404 提示）
    payload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/data", StaticFiles(directory=payload_dir), name="data")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/v1/healthz")
    def healthz() -> dict:
        return {"status": "ok", "data_dir": str(data_dir), "web_built": (payload_dir / "meta.json").exists()}

    @app.get("/api/v1/meta")
    def meta() -> dict:
        path = payload_dir / "meta.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="看板数据未构建：请先执行 `policesight web build --data-dir <目录>`")
        return json.loads(path.read_text(encoding="utf-8"))

    def _start_date() -> date:
        if cache["start"] is None:
            meta_path = payload_dir / "meta.json"
            if meta_path.exists():
                cache["start"] = date.fromisoformat(json.loads(meta_path.read_text(encoding="utf-8"))["start_date"])
            else:
                cache["start"] = date(2026, 3, 1)
        return cache["start"]  # type: ignore[return-value]

    @app.get("/api/v1/cases")
    def cases(
        limit: int = Query(default=default_limit, ge=1, le=2000),
        offset: int = Query(default=0, ge=0),
        type: str | None = Query(default=None, description="案件类型（精确匹配）"),
        district: str | None = Query(default=None, description="片区（精确匹配）"),
        day_from: float | None = Query(default=None, ge=0, description="起始日序号"),
        day_to: float | None = Query(default=None, ge=0, description="结束日序号"),
    ) -> dict:
        csv_path = data_dir / "cases.csv"
        if not csv_path.exists():
            raise HTTPException(status_code=404, detail="未找到 cases.csv：请先生成数据（policesight data generate）")
        if cache["rows"] is None:
            with open(csv_path, encoding="utf-8-sig", newline="") as fh:
                cache["rows"] = list(csv.DictReader(fh))
        rows: list[dict] = cache["rows"]  # type: ignore[assignment]
        day_cache: dict[str, int] = cache["days"]  # type: ignore[assignment]
        start = _start_date()

        selected: list[dict] = []
        for row in rows:
            if type and row["type"] != type:
                continue
            if district and row["district"] != district:
                continue
            if day_from is not None or day_to is not None:
                key = row["case_id"]
                value = day_cache.get(key)
                if value is None:
                    value = (date.fromisoformat(row["time"][:10]) - start).days
                    day_cache[key] = value
                if day_from is not None and value < day_from:
                    continue
                if day_to is not None and value > day_to:
                    continue
            selected.append(row)
        page = selected[offset : offset + limit]
        return {"total": len(selected), "limit": limit, "offset": offset, "items": page}

    return app
