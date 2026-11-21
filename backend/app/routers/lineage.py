"""记录级血缘的版本化导出接口：按黄金版本回溯字段来源，输出可核对的 CSV 与导出批次。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services.record_lineage import RecordLineageService

# 先注册在通用资源路由之前：/api/record_lineage/{entry_id} 会把 version-export 当成 id，
# 因此这些固定路径必须由本路由先匹配。
router = APIRouter(prefix="/api/record_lineage", tags=["记录级血缘"])

PARAM_COLUMNS = ["golden_id", "version", "来源系统", "字段路径", "取值时间", "生效时间", "失效时间"]
RESULT_COLUMNS = [
    "字段路径", "来源系统", "来源记录", "原始值", "变换证据",
    "取值时间", "生效时间", "失效时间", "血缘编号", "历史条数", "核对状态",
]


def _csv_cell(value: Any) -> Any:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _render_csv(payload: dict[str, Any]) -> str:
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["# 历史血缘导出"])
    writer.writerow(["导出编号", payload["导出编号"]])
    writer.writerow(["黄金ID", payload["黄金ID"]])
    writer.writerow(["目标版本", payload["目标版本"]])
    writer.writerow(["版本编号", payload["版本依据"]["版本编号"]])
    writer.writerow(["版本时间", payload["版本依据"]["版本时间"]])
    writer.writerow(["有效时间起", payload["有效时间"]["起"]])
    writer.writerow(["有效时间止", payload["有效时间"]["止"] or "持续有效"])
    scope = payload["核对范围"]
    writer.writerow(["可核对字段", "|".join(scope["可核对字段"])])
    writer.writerow(["缺失原始值字段", "|".join(scope["缺失原始值字段"])])
    writer.writerow(["缺失变换证据字段", "|".join(scope["缺失变换证据字段"])])
    writer.writerow(["缺失来源字段", "|".join(scope["缺失来源字段"])])
    writer.writerow(["核对说明", scope["说明"]])
    writer.writerow([])
    writer.writerow(["## 历史字段与来源"])
    writer.writerow(RESULT_COLUMNS)
    for field in payload["字段"]:
        writer.writerow([_csv_cell(field.get(column, "")) for column in RESULT_COLUMNS])
    writer.writerow([])
    writer.writerow(["## 来源系统时间线（确认后来加入的来源不在本版本内）"])
    writer.writerow(["来源系统", "最早生效时间", "纳入本版本", "晚于版本加入"])
    for item in payload["来源系统时间线"]:
        writer.writerow([
            _csv_cell(item["来源系统"]), _csv_cell(item["最早生效时间"]),
            "是" if item["纳入本版本"] else "否",
            "是" if item["晚于版本加入"] else "否",
        ])
    writer.writerow([])
    writer.writerow(["## 窗口外血缘（历史证据原样保留，不纳入本次版本）"])
    writer.writerow(PARAM_COLUMNS)
    for lineage in payload["窗口外血缘"]:
        record = {"golden_id": payload["黄金ID"], "version": payload["目标版本"], **lineage}
        writer.writerow([_csv_cell(record.get(column, "")) for column in PARAM_COLUMNS])
    return output.getvalue()


@router.get("/version-export")
def export_lineage_for_version(
    golden_id: str = Query(..., description="黄金ID"),
    version: str = Query(..., description="目标黄金版本号"),
    format: str = Query(default="csv", pattern="^(csv|json)$",
                        description="csv 供下载签收，json 供页面先看核对范围"),
) -> Any:
    """按指定黄金版本导出历史血缘，供审计批次复核签收或继续补证。"""
    payload = RecordLineageService().export_lineage_for_version(golden_id, version)
    if not payload.get("ok"):
        raise HTTPException(status_code=404, detail=payload.get("reason", "历史血缘导出失败"))
    if format == "json":
        return payload
    filename = f"lineage_{golden_id}_v{version}.csv"
    return StreamingResponse(
        iter([_render_csv(payload)]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/version-exports")
def list_version_exports(golden_id: str | None = Query(default=None)) -> dict[str, Any]:
    """列出已生成的历史血缘导出批次，便于审计下载后核对。"""
    rows = RecordLineageService().list_version_exports(golden_id)
    return {"items": rows, "total": len(rows)}
