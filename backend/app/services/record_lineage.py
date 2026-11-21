"""记录级血缘领域服务：字段路径关联、变换追溯、血缘图谱构建与按版本回溯导出。"""
from __future__ import annotations

import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


def _parse_time(value: Any) -> datetime.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None

def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _same_version(left: Any, right: Any) -> bool:
    """版本号允许 1 与 1.0 两种写法互相匹配，其余按字符串严格比较。"""
    left_text = str(left if left is not None else "").strip()
    right_text = str(right if right is not None else "").strip()
    if left_text == right_text:
        return True
    try:
        return float(left_text) == float(right_text)
    except ValueError:
        return False


def _version_at(golden_id: str, version: str) -> tuple[dict[str, Any] | None, str | None]:
    """定位黄金记录的指定版本，并给出该版本在版本链中的有效窗口。

    版本时间只标明版本生成时刻；窗口终点取同一黄金ID下更晚版本里
    版本时间最早的一条（即该版本被替代的时刻），没有后继版本则说明
    持续有效、窗口终点为空。
    """
    rows = store.rows("mdm_version")
    candidates = [
        row for row in rows
        if str(row.get("黄金ID")) == str(golden_id)
        and _same_version(row.get("版本号"), version)
    ]
    if not candidates:
        return None, f"黄金记录 {golden_id} 没有版本 {version} 的版本记录"
    # 同一版本号若被重复登记，取版本时间最早的一条作为该版本的快照依据。
    # 复制一份再补算窗口终点，避免把派生字段写回版本存储。
    target = dict(min(candidates, key=lambda r: str(r.get("版本时间", ""))))
    target_time = _parse_time(target.get("版本时间"))
    successors: list[datetime.datetime] = []
    for row in rows:
        if str(row.get("黄金ID")) != str(golden_id):
            continue
        row_time = _parse_time(row.get("版本时间"))
        if row_time is None or target_time is None:
            continue
        if row_time > target_time:
            successors.append(row_time)
    if successors:
        target["_有效截止"] = min(successors).isoformat()
    else:
        target["_有效截止"] = ""
    return target, None



class RecordLineageService(BaseModuleService):
    MODULE = "record_lineage"
    ENTITY = "血缘记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["血缘编号", "黄金ID", "来源记录", "来源系统", "字段路径", "原始值",
                   "变换记录", "生效时间", "失效时间", "复核"]
    REQUIRED_FIELDS = ["血缘编号", "黄金ID", "来源记录"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已停用"]
    ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "停用记录": "已停用"}
    NEGATIVE_ACTIONS = ["停用记录"]

    def record_field_lineage(self, golden_id: str, source_record_id: str,
                               source_system: str, field_path: str,
                               transformations: list[str],
                               raw_value: str = "",
                               effective_time: str | None = None,
                               expire_time: str = "",
                               version: str = "",
                               review: str = "") -> dict[str, Any]:
        """记录字段级血缘：将黄金记录字段关联到原始来源记录的字段路径。

        关联血缘记录到record_lineage存储，记录每个黄金字段的完整
        来源路径和变换历史，构建端到端的字段级追溯链路。
        原始值、生效窗口、所属版本与复核批次都是可选证据：调用方没有
        提供时如实留空，后续版本导出会据此说明可核对范围。
        """
        rows = store.rows(self.MODULE)
        lineage_id = f"LINE-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "血缘编号": lineage_id,
            "黄金ID": golden_id,
            "来源记录": source_record_id,
            "来源系统": source_system,
            "字段路径": field_path,
            "原始值": raw_value,
            "变换记录": "|".join(transformations),
            "生效时间": effective_time or datetime.datetime.utcnow().isoformat(),
            "失效时间": expire_time,
            "所属版本": version,
            "复核": review,
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "transform_count": len(transformations),
        }
        rows.append(entry)
        # 关联血缘记录：建立黄金字段到原始来源的完整追溯链路
        return {"ok": True, "lineage": entry}

    def query_field_lineage(self, golden_id: str) -> list[dict[str, Any]]:
        """查询指定黄金记录的所有字段级血缘关联。

        按黄金ID查询血缘记录存储，获取每条字段从来源系统、
        原始记录到黄金记录的完整关联路径和变换历史。
        """
        rows = store.rows(self.MODULE)
        lineage = [
            row for row in rows
            if row.get("黄金ID") == golden_id and row.get("status") == "已生效"
        ]
        # 查询血缘关联：获取黄金记录的完整字段级追溯路径
        lineage.sort(key=lambda r: r.get("生效时间", ""))
        return lineage

    def build_lineage_graph(self, golden_id: str) -> dict[str, Any]:
        """构建血缘图谱：基于字段级血缘记录生成DAG关系图。

        查询黄金记录的所有血缘记录，关联来源系统和字段路径信息，
        构建从来源记录到黄金记录的完整血缘有向无环图。
        """
        lineages = self.query_field_lineage(golden_id)
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        visited = set()
        for lineage in lineages:
            source = lineage.get("来源记录", "")
            field = lineage.get("字段路径", "")
            if source and source not in visited:
                visited.add(source)
                nodes.append({"id": source, "type": "source_record", "system": lineage.get("来源系统")})
            field_node_id = f"{golden_id}:{field}"
            if field_node_id not in visited:
                visited.add(field_node_id)
                nodes.append({"id": field_node_id, "type": "golden_field", "field": field})
            edges.append({
                "from": source,
                "to": field_node_id,
                "transformations": (lineage.get("变换记录", "")).split("|"),
            })
        # 构建血缘图谱：关联来源记录和字段路径生成DAG关系图
        return {"golden_id": golden_id, "nodes": nodes, "edges": edges}

    def validate_lineage_completeness(self, golden_id: str,
                                       expected_sources: list[str]) -> dict[str, Any]:
        """校验血缘完整性：确认黄金记录的每条来源都有字段级血缘关联。

        查询血缘记录存储，校验每个预期来源是否都有对应的字段
        路径血缘记录，输出血缘完备性校验报告。
        """
        lineages = self.query_field_lineage(golden_id)
        covered = set()
        for lineage in lineages:
            covered.add(lineage.get("来源记录", ""))
        missing = [s for s in expected_sources if s not in covered]
        return {
            "golden_id": golden_id,
            "expected_sources": len(expected_sources),
            "lineage_entries": len(lineages),
            "covered_sources": len(covered),
            "missing_sources": missing,
            "completeness": round(len(covered) / max(len(expected_sources), 1) * 100, 2),
        }

    def expire_lineage_entries(self, golden_id: str, expire_reason: str) -> int:
        """失效血缘记录：当黄金记录更新时标记旧血缘为失效状态。

        将指定黄金记录的所有已生效血缘记录标记为已停用，
        并设置失效时间，保留历史追溯但不再用于当前关联图谱。
        """
        rows = store.rows(self.MODULE)
        expired = 0
        for row in rows:
            if row.get("黄金ID") == golden_id and row.get("status") == "已生效":
                row["status"] = "已停用"
                row["失效时间"] = datetime.datetime.utcnow().isoformat()
                row["expire_reason"] = expire_reason
                expired += 1
        return expired

    def export_lineage_trace(self, golden_id: str) -> dict[str, Any]:
        """导出血缘追溯：将黄金记录的完整字段级血缘导出供审计分析。"""
        lineages = self.query_field_lineage(golden_id)
        trace: dict[str, list[dict[str, Any]]] = {}
        for lineage in lineages:
            field = lineage.get("字段路径", "")
            if field not in trace:
                trace[field] = []
            trace[field].append({
                "source_system": lineage.get("来源系统"),
                "source_record": lineage.get("来源记录"),
                "transformations": (lineage.get("变换记录", "")).split("|"),
                "effective_time": lineage.get("生效时间"),
            })
        # 导出血缘追溯：构建字段级完整来源追溯链路
        return {"golden_id": golden_id, "field_trace": trace, "total_entries": len(lineages)}

    def query_lineage_by_system(self, source_system: str) -> list[dict[str, Any]]:
        """查询给定来源系统影响的所有黄金记录，反向追溯血缘。"""
        rows = store.rows(self.MODULE)
        return [
            row for row in rows
            if row.get("来源系统") == source_system and row.get("status") == "已生效"
        ]

    def export_lineage_for_version(self, golden_id: str, version: str) -> dict[str, Any]:
        """按指定黄金版本导出历史血缘：以版本有效窗口匹配字段血缘记录。

        - 版本提供历史字段的时间与版本依据，窗口起点为版本时间；
        - 窗口起点之前生效的记录都算该版本的历史证据，按来源保留历次变换；
        - 窗口起点之后才生效的来源（如后来接入的客服系统）不进入历史字段，
          只列在“窗口外血缘”里，存储内容不做任何改动；
        - 版本声明的变更字段若在窗口内没有任何来源凭证，如实列入“缺失来源”，
          交给审计继续补证，而不是用现时血补齐。
        """
        version_row, error = _version_at(golden_id, version)
        if version_row is None:
            return {"ok": False, "reason": error}

        effective_from = version_row.get("版本时间") or ""
        window_start = _parse_time(effective_from)
        effective_to = version_row.get("_有效截止") or ""

        # 快照是只读证据：导出过程中不能改动存储里的血缘记录
        golden_rows = [
            dict(row) for row in store.rows(self.MODULE)
            if str(row.get("黄金ID")) == str(golden_id)
        ]
        matched: list[dict[str, Any]] = []
        out_of_window: list[dict[str, Any]] = []
        for row in golden_rows:
            # 历史证据原样保留：这里只决定纳入还是排除，从不改动存储里的记录
            start_time = _parse_time(row.get("生效时间"))
            if (
                window_start is not None
                and start_time is not None
                and start_time <= window_start
            ):
                matched.append(row)
            else:
                out_of_window.append(row)

        fields = self._group_export_fields(matched, window_start)

        missing_original = [
            f"{f['字段路径']}@{f['来源系统']}" for f in fields
            if f["核对状态"] == "缺原始值，需补证"
        ]
        missing_transform = [
            f"{f['字段路径']}@{f['来源系统']}" for f in fields
            if f["核对状态"] == "缺变换证据，可核对原始值"
        ]
        missing_source = self._missing_source_fields(version_row, golden_rows, matched)
        verifiable = _dedupe([
            f["字段路径"] for f in fields if f["核对状态"] == "可核对"
        ])

        version_label = str(version_row.get("版本号", version))
        export_id = f"LINEXP-{golden_id}-V{version_label}-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        export_row = {
            "id": max((int(r.get("id", 0)) for r in store.rows("lineage_export")), default=0) + 1,
            "导出编号": export_id,
            "黄金ID": golden_id,
            "目标版本": str(version_row.get("版本号", version)),
            "版本编号": version_row.get("版本编号", ""),
            "版本时间": effective_from,
            "有效时间起": effective_from,
            "有效时间止": effective_to,
            "批次": version_row.get("变更批次", ""),
            "字段数": len(fields),
            "血缘条数": len(matched),
            "可核对字段": "|".join(verifiable),
            "缺失原始值字段": "|".join(missing_original),
            "缺失变换证据字段": "|".join(missing_transform),
            "缺失来源字段": "|".join(missing_source),
            "证据缺失": bool(missing_original or missing_transform or missing_source),
            "导出时间": datetime.datetime.utcnow().isoformat(),
            "status": "已导出",
            "pending": False,
            "abnormal": bool(missing_original or missing_transform or missing_source),
        }
        store.rows("lineage_export").append(export_row)

        return {
            "ok": True,
            "导出编号": export_id,
            "黄金ID": golden_id,
            "目标版本": str(version_row.get("版本号", version)),
            "版本依据": {
                "版本编号": version_row.get("版本编号"),
                "版本号": version_row.get("版本号"),
                "版本时间": effective_from,
                "变更字段": version_row.get("变更字段", ""),
                "变更批次": version_row.get("变更批次", ""),
            },
            "有效时间": {"起": effective_from, "止": effective_to},
            "字段": fields,
            "核对范围": {
                "可核对字段": verifiable,
                "缺失原始值字段": missing_original,
                "缺失变换证据字段": missing_transform,
                "缺失来源字段": missing_source,
                "说明": self._scope_note(
                    verifiable,
                    [f for f in fields if f["核对状态"] == "缺变换证据，可核对原始值"],
                    [f for f in fields if f["核对状态"] == "缺原始值，需补证"],
                    missing_source,
                ),
            },
            "来源系统时间线": self._source_timeline(golden_rows, matched, out_of_window),
            "纳入血缘": matched,
            "窗口外血缘": out_of_window,
            "历史证据": {
                "保留方式": "原样存留",
                "纳入条数": len(matched),
                "窗口外条数": len(out_of_window),
            },
        }

    def _group_export_fields(self, lineages: list[dict[str, Any]],
                               window_start: datetime.datetime | None) -> list[dict[str, Any]]:
        """按“字段路径 + 来源系统”分组，保留窗口起点之前的历次变换。

        取值时点固定在版本时间：只有覆盖该时点、且未被更晚记录接替的
        那条血缘才作为版本当时的字段值；更早的记录仍完整列在历史里。
        """
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in lineages:
            key = (str(row.get("字段路径", "")), str(row.get("来源系统", "")))
            grouped.setdefault(key, []).append(row)

        fields: list[dict[str, Any]] = []
        for (path, source_system), rows in grouped.items():
            rows.sort(key=lambda r: (str(r.get("生效时间", "")), int(r.get("id", 0))))
            active = [
                row for row in rows
                if window_start is not None
                and (
                    not row.get("失效时间")
                    or (_parse_time(row.get("失效时间")) or window_start) > window_start
                )
            ]
            current = active[-1] if active else None
            if current is None:
                status = "缺原始值，需补证"
            elif not str(current.get("原始值", "")).strip():
                status = "缺原始值，需补证"
            elif not str(current.get("变换记录", "")).strip():
                status = "缺变换证据，可核对原始值"
            else:
                status = "可核对"
            fields.append({
                "字段路径": path,
                "来源系统": source_system,
                "来源记录": (current or rows[-1]).get("来源记录", ""),
                "原始值": (current or {}).get("原始值", ""),
                "变换证据": (current or {}).get("变换记录", ""),
                "取值时间": (current or {}).get("生效时间", ""),
                "生效时间": (current or rows[-1]).get("生效时间", ""),
                "失效时间": (current or rows[-1]).get("失效时间", ""),
                "血缘编号": (current or {}).get("血缘编号", ""),
                "核对状态": status,
                "历史条数": len(rows),
                "历史": [
                    {
                        "血缘编号": r.get("血缘编号"),
                        "来源系统": r.get("来源系统"),
                        "来源记录": r.get("来源记录"),
                        "原始值": r.get("原始值", ""),
                        "变换记录": r.get("变换记录", ""),
                        "生效时间": r.get("生效时间"),
                        "失效时间": r.get("失效时间"),
                        "status": r.get("status"),
                        "所属版本": r.get("所属版本", ""),
                        "复核": r.get("复核", ""),
                    }
                    for r in rows
                ],
            })
        fields.sort(key=lambda f: (f["字段路径"], f["来源系统"]))
        return fields

    @staticmethod
    def _source_timeline(golden_rows: list[dict[str, Any]],
                          matched: list[dict[str, Any]],
                          out_of_window: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按来源系统给出最早生效时间，用来确认后来加入的来源没有混进更早的版本。"""
        earliest: dict[str, str] = {}
        for row in golden_rows:
            system = str(row.get("来源系统", ""))
            seen = str(row.get("生效时间", ""))
            if not system:
                continue
            if system not in earliest or seen < earliest[system]:
                earliest[system] = seen
        matched_systems = {str(row.get("来源系统", "")) for row in matched}
        late_systems = {str(row.get("来源系统", "")) for row in out_of_window} - matched_systems
        return [
            {
                "来源系统": system,
                "最早生效时间": earliest[system],
                "纳入本版本": system in matched_systems,
                "晚于版本加入": system in late_systems and system not in matched_systems,
            }
            for system in sorted(earliest)
        ]

    @staticmethod
    def _missing_source_fields(version_row: dict[str, Any],
                               golden_rows: list[dict[str, Any]],
                               matched: list[dict[str, Any]]) -> list[str]:
        """版本声明的变更字段若在窗口内没有任何来源凭证，逐项列出待补证。"""
        known_paths = {str(row.get("字段路径", "")) for row in golden_rows}
        covered_paths = {str(row.get("字段路径", "")) for row in matched}
        missing: list[str] = []
        for raw in str(version_row.get("变更字段", "")).split(","):
            name = raw.strip()
            if not name:
                continue
            candidates = [
                path for path in known_paths
                if path == name or path.rsplit(".", 1)[-1] == name
            ]
            if not candidates:
                missing.append(name)
            elif not any(path in covered_paths for path in candidates):
                missing.append(candidates[0])
        return _dedupe(missing)

    @staticmethod
    def _scope_note(verifiable: list[str], missing_transform_fields: list[dict[str, Any]],
                    missing_value_fields: list[dict[str, Any]],
                    missing_source_fields: list[str]) -> str:
        if not missing_transform_fields and not missing_value_fields and not missing_source_fields:
            return "全部字段均带原始值与变换证据，可按导出内容逐项复核签收。"
        parts = []
        if verifiable:
            parts.append(f"可核对：{'、'.join(verifiable)}")
        if missing_transform_fields:
            parts.append(
                "变换证据缺失、只能核对原始值："
                + "、".join(f"{f['字段路径']}@{f['来源系统']}" for f in missing_transform_fields)
            )
        if missing_value_fields:
            parts.append(
                "版本时点无仍在生效的原始值："
                + "、".join(f"{f['字段路径']}@{f['来源系统']}" for f in missing_value_fields)
            )
        if missing_source_fields:
            parts.append(f"窗口内无任何来源凭证：{'、'.join(missing_source_fields)}")
        parts.append("缺证部分需回到来源系统继续补证后再签收。")
        return "；".join(parts)

    def list_version_exports(self, golden_id: str | None = None) -> list[dict[str, Any]]:
        """查询历史血缘导出批次，供审计批次核对与复核签收。"""
        rows = store.rows("lineage_export")
        if golden_id:
            rows = [row for row in rows if str(row.get("黄金ID")) == str(golden_id)]
        return sorted(rows, key=lambda r: str(r.get("导出时间", "")), reverse=True)
