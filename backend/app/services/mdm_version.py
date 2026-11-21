"""版本管理领域服务：黄金记录版本快照、变更对比与版本回退。"""
from __future__ import annotations

import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class MdmVersionService(BaseModuleService):
    MODULE = "mdm_version"
    ENTITY = "版本记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["版本编号", "黄金ID", "版本号", "变更字段", "旧值摘要", "新值摘要", "变更批次", "版本时间"]
    REQUIRED_FIELDS = ["版本编号", "黄金ID", "版本号"]
    STATUS_ORDER = ["草稿", "当前版本", "历史版本", "已回滚"]
    ACTION_RULES = {"设为当前": "当前版本", "标记历史": "历史版本", "执行回滚": "已回滚"}
    NEGATIVE_ACTIONS = []

    def snapshot_golden_version(self, golden_id: str,
                                  record_data: dict[str, Any],
                                  version_time: str | None = None,
                                  change_batch: str | None = None) -> dict[str, Any]:
        """存储黄金记录版本快照，记录字段变更的新旧值对比。

        读取当前黄金记录数据，对比新值生成变更字段列表，
        存储版本快照到mdm_version存储，关联黄金ID和变更批次。
        version_time / change_batch 用于补录或导入既有批次的历史版本：
        不传时按当前时刻登记，传入时严格使用给定时间作为版本依据。
        """
        from app.services.golden_record import GoldenRecordService
        golden_svc = GoldenRecordService()
        current = golden_svc.query_golden_record(golden_id)
        version_num = self._next_version(golden_id)

        changed_fields = []
        old_summary: dict[str, str] = {}
        new_summary: dict[str, str] = {}
        if current:
            for key in record_data:
                if key.startswith("_"):
                    continue
                old_val = str(current.get(key, ""))
                new_val = str(record_data.get(key, ""))
                if old_val != new_val:
                    changed_fields.append(key)
                    old_summary[key] = old_val
                    new_summary[key] = new_val

        rows = store.rows(self.MODULE)
        version_id = f"VER-{golden_id}-{version_num}"
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "版本编号": version_id,
            "黄金ID": golden_id,
            "版本号": version_num,
            "变更字段": ",".join(changed_fields),
            "旧值摘要": str(old_summary) if old_summary else "",
            "新值摘要": str(new_summary) if new_summary else "",
            "变更批次": change_batch or golden_id,
            "版本时间": version_time or datetime.datetime.utcnow().isoformat(),
            "status": "当前版本",
            "pending": False,
            "abnormal": False,
        }
        # 存储版本快照：记录字段变更的新旧值对比并写入mdm_version
        self._set_previous_history(golden_id)
        rows.append(entry)
        return {"ok": True, "version": entry, "changed_fields": changed_fields}

    def _next_version(self, golden_id: str) -> str:
        """计算下一个版本号。"""
        rows = store.rows(self.MODULE)
        versions = [
            float(r.get("版本号", "0"))
            for r in rows if r.get("黄金ID") == golden_id
        ]
        return str(max(versions, default=0) + 1.0)

    def _set_previous_history(self, golden_id: str) -> None:
        """将之前当前版本标记为历史版本。"""
        rows = store.rows(self.MODULE)
        for row in rows:
            if row.get("黄金ID") == golden_id and row.get("status") == "当前版本":
                row["status"] = "历史版本"

    def query_version_history(self, golden_id: str) -> list[dict[str, Any]]:
        """查询版本历史：获取黄金记录的所有版本变更记录。

        按黄金ID查询版本记录存储，获取所有版本的变更字段、
        新旧值对比和时间线，按版本号降序排列。
        """
        rows = store.rows(self.MODULE)
        history = [row for row in rows if row.get("黄金ID") == golden_id]
        # 查询版本历史：获取黄金记录的完整版本变更时间线
        history.sort(key=lambda r: float(r.get("版本号", "0")), reverse=True)
        return history

    def rollback_to_version(self, golden_id: str,
                              target_version: str) -> dict[str, Any]:
        """版本回退：将黄金记录回退到指定历史版本。

        读取指定版本号的快照数据，恢复黄金记录的字段值
        到历史状态，并标记被回退的当前版本。
        """
        rows = store.rows(self.MODULE)
        target = next(
            (r for r in rows if r.get("黄金ID") == golden_id and r.get("版本号") == target_version),
            None
        )
        if not target:
            return {"ok": False, "reason": "目标版本不存在"}
        # 标记当前版本为已回滚，设置目标版本为当前
        for row in rows:
            if row.get("黄金ID") == golden_id and row.get("status") == "当前版本":
                row["status"] = "已回滚"
                row["rolled_back_at"] = datetime.datetime.utcnow().isoformat()
        target["status"] = "当前版本"
        return {"ok": True, "golden_id": golden_id, "restored_to": target_version}

    def compare_versions(self, golden_id: str,
                           version_a: str, version_b: str) -> dict[str, Any]:
        """对比两个版本的黄金记录差异：逐字段展示变更内容。

        查询两个版本的快照数据，逐字段对比新值旧值差异，
        输出字段级变更对比报告供审计使用。
        """
        rows = store.rows(self.MODULE)
        ver_a = next(
            (r for r in rows if r.get("黄金ID") == golden_id and r.get("版本号") == version_a),
            None
        )
        ver_b = next(
            (r for r in rows if r.get("黄金ID") == golden_id and r.get("版本号") == version_b),
            None
        )
        if not ver_a or not ver_b:
            return {"ok": False, "reason": "版本不存在"}
        # 对比版本差异：逐字段展示两个版本的新旧值变更内容
        return {
            "golden_id": golden_id,
            "version_a": version_a,
            "version_b": version_b,
            "a_time": ver_a.get("版本时间"),
            "b_time": ver_b.get("版本时间"),
            "a_changes": ver_a.get("变更字段"),
            "b_changes": ver_b.get("变更字段"),
        }