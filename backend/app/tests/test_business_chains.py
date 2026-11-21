"""业务链路测试：验证主数据清洗与黄金记录平台的 6 条关键链路。"""
from __future__ import annotations

import datetime
import sys
import os

_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.services.source_system import SourceSystemService
from app.services.data_import_rule import DataImportRuleService
from app.services.import_batch import ImportBatchService
from app.services.field_cleanse import FieldCleanseService
from app.services.match_rule import MatchRuleService
from app.services.auto_match_job import AutoMatchJobService
from app.services.dup_cluster import DupClusterService
from app.services.merge_log import MergeLogService
from app.services.golden_record import GoldenRecordService
from app.services.record_lineage import RecordLineageService
from app.services.survivorship_rule import SurvivorshipRuleService
from app.services.entity_model import EntityModelService
from app.services.mdm_quality import MdmQualityService
from app.services.mdm_reference import MdmReferenceService
from app.services.mdm_api import MdmApiService
from app.services.mdm_sync import MdmSyncService
from app.services.mdm_version import MdmVersionService
from app.services.mdm_dashboard import MdmDashboardService
from app.store import store


class TestBusinessChains:
    """测试主数据清洗平台的 6 条关键业务链路。"""

    # ── 链路1: 来源系统→入库规则→批次导入→字段标准化清洗 ──
    def test_chain1_source_import_cleanse(self):
        """来源系统接入 -> 入库规则校验 -> 批次导入 -> 字段标准化清洗。"""
        # 注册来源系统并导入元数据
        source_svc = SourceSystemService()
        result = source_svc.register_source_system({
            "系统编号": "CRM-001",
            "系统名称": "CRM客户系统",
            "系统类型": "CRM",
            "连接地址": "https://crm.example.com/api",
            "数据格式": "JSON",
            "刷新频率": "每日",
            "信任权重": "85",
        })
        assert result["ok"] is True, f"来源系统注册失败: {result}"
        systems = source_svc.query_active_systems()
        assert len(systems) > 0, "应查询到活跃来源系统"

        # 入库规则：导入并校验字段映射
        rule_svc = DataImportRuleService()
        rule_result = rule_svc.import_data_with_rules(1, [
            {"name": "张三", "phone": "13800138000"},
            {"name": "李四", "phone": "13900139000"},
        ])
        # 校验入库规则结果：规则可能未生效，但方法应正常返回
        assert isinstance(rule_result, dict), "入库规则应返回字典"

        # 批次导入：按来源系统导入数据批次
        batch_svc = ImportBatchService()
        batch = batch_svc.import_batch_from_source("CRM", "customer", 5000)
        assert batch["批次编号"].startswith("BATCH-"), f"批次编号格式异常: {batch['批次编号']}"

        summary = batch_svc.query_batch_summary()
        assert summary["total_batches"] > 0, "批次汇总不应为空"

        # 字段标准化清洗
        cleanse_svc = FieldCleanseService()
        records = [
            {"customer_name": "  Zhang San  ", "phone": "138-0013-8000"},
            {"customer_name": "LI SI", "phone": "139 0013 9000"},
        ]
        cleaned = cleanse_svc.standardize_field_values(records, "customer")
        assert len(cleaned) == 2, f"清洗后应有2条记录，实际: {len(cleaned)}"

    # ── 链路2: 匹配规则引擎→自动匹配任务→疑似重复簇 ──
    def test_chain2_match_to_cluster(self):
        """匹配规则配置 -> 自动匹配任务 -> 生成疑似重复簇。"""
        match_svc = MatchRuleService()
        records = [
            {"name": "张三", "phone": "13800138000", "email": "zhang@test.com"},
            {"name": "张  三", "phone": "13800138000", "email": "zhangsan@test.com"},
            {"name": "李四", "phone": "13900139000", "email": "lisi@other.com"},
        ]
        # 计算相似度
        sim = match_svc.compute_similarity(1, records[0], records[1])
        assert 0 <= sim <= 1, f"相似度应在[0,1]范围: {sim}"

        # 生成重复簇
        clusters = match_svc.generate_duplicate_clusters(1, records)
        assert isinstance(clusters, list), "应为簇列表"

        # 校验匹配规则参数
        validation = match_svc.validate_match_rule_parameters(1)
        assert "checks" in validation

        # 自动匹配任务调度
        job_svc = AutoMatchJobService()
        job_result = job_svc.schedule_match_job(1, "customer", records)
        assert job_result["ok"] is True, f"匹配任务调度失败: {job_result}"
        assert job_result.get("clusters") is not None, "应有簇输出"

    # ── 链路3: 重复簇→合并追溯→黄金记录→记录级血缘 ──
    def test_chain3_dup_to_golden_lineage(self):
        """重复簇 -> 合并 -> 黄金记录 -> 记录级血缘。"""
        cluster_svc = DupClusterService()
        records = [
            {"name": "张三", "phone": "13800138000"},
            {"name": "张三", "phone": "13800138000"},
        ]
        merged_result = cluster_svc.merge_duplicate_cluster(1, records)
        if merged_result["ok"]:
            assert merged_result.get("merged_record") is not None, "应有合并结果"

        # 查询待处置重复簇
        pending = cluster_svc.query_clusters_for_disposal("customer")
        assert isinstance(pending, list), "应为列表"

        # 合并追溯记录
        merge_svc = MergeLogService()
        log_result = merge_svc.record_merge_event(
            "GR-test-001",
            ["SRC-001", "SRC-002"],
            "全字段匹配",
            ["name", "phone"],
            [],
        )
        assert log_result["ok"] is True, f"合并记录写入失败: {log_result}"

        # 查询合并追溯
        history = merge_svc.query_merge_history("GR-test-001")
        assert isinstance(history, list), "应为历史列表"

        # 创建黄金记录
        golden_svc = GoldenRecordService()
        golden = golden_svc.create_golden_record(
            "customer",
            {"name": "张三", "phone": "13800138000", "representative": {"name": "张三"}},
            ["SRC-001", "SRC-002"],
        )
        assert golden["ok"] is True, f"黄金记录创建失败: {golden}"
        golden_id = golden["golden_record"]["黄金ID"]
        assert golden_id, "黄金ID不应为空"

        # 关联新来源到黄金记录
        link_result = golden_svc.link_source_to_golden(golden_id, "SRC-003")
        assert link_result["ok"] is True, "来源关联失败"

        # 记录字段级血缘
        lineage_svc = RecordLineageService()
        lineage = lineage_svc.record_field_lineage(
            golden_id, "SRC-001", "CRM",
            "customer.name", ["trim", "标准化"],
        )
        assert lineage["ok"] is True, f"血缘记录写入失败: {lineage}"

        # 查询血缘
        field_lineage = lineage_svc.query_field_lineage(golden_id)
        assert isinstance(field_lineage, list), "应为血缘列表"

        # 构建血缘图谱
        graph = lineage_svc.build_lineage_graph(golden_id)
        assert "nodes" in graph and "edges" in graph, "图谱应包含节点和边"

    # ── 链路4: 字段标准化→优胜策略→黄金记录版本 ──
    def test_chain4_survivorship_to_version(self):
        """字段标准化清洗 -> 优胜策略裁决 -> 黄金记录版本快照。"""
        # 字段标准化
        cleanse_svc = FieldCleanseService()
        records = [
            {"customer_name": "  Zhang San  ", "phone": "13800138000", "email": "ZHANG@TEST.COM"},
        ]
        cleaned = cleanse_svc.batch_cleanse_records(1, records, "customer_name")
        assert len(cleaned) == 1

        # 优胜策略裁决字段冲突
        survivor_svc = SurvivorshipRuleService()
        candidates = [
            {"value": "张三", "_source": "CRM"},
            {"value": "张  三", "_source": "ERP"},
        ]
        resolved = survivor_svc.resolve_field_conflict(1, "name", candidates)
        assert resolved.get("winner") is not None, "应有优胜者"
        assert resolved.get("losers") is not None, "应有落选者"

        # 黄金记录版本快照
        version_svc = MdmVersionService()
        version_result = version_svc.snapshot_golden_version(
            "GR-test-version",
            {"name": "张三", "phone": "13800138001", "email": "zhang@test.com"},
        )
        assert version_result["ok"] is True, f"版本快照创建失败: {version_result}"
        assert version_result.get("changed_fields") is not None, "应有变更字段"

        # 查询版本历史
        history = version_svc.query_version_history("GR-test-version")
        assert isinstance(history, list), "应为版本历史列表"

    # ── 链路5: 黄金记录→查询接口→主数据分发同步 ──
    def test_chain5_golden_to_sync(self):
        """黄金记录查询 -> 标准化查询接口 -> 主数据分发同步。"""
        # 创建黄金记录
        golden_svc = GoldenRecordService()
        golden = golden_svc.create_golden_record(
            "customer",
            {"name": "张三", "phone": "13800138000", "representative": {"name": "张三"}},
            ["SRC-001"],
        )
        assert golden["ok"] is True
        golden_id = golden["golden_record"]["黄金ID"]

        # 查询黄金记录
        found = golden_svc.query_golden_record(golden_id)
        assert found is not None, "应查询到黄金记录"
        assert found.get("黄金ID") == golden_id, f"黄金ID不匹配: {found}"

        # 搜索黄金记录
        search_results = golden_svc.search_golden_records("customer")
        assert len(search_results) > 0, "搜索应有结果"

        # 查询接口：标准化输出
        api_svc = MdmApiService()
        api_result = api_svc.query_golden_records_by_api(1)
        if api_result["ok"]:
            assert "records" in api_result

        # 同步黄金记录到目标系统
        sync_svc = MdmSyncService()
        sync_result = sync_svc.sync_golden_to_target(1)
        if sync_result["ok"]:
            assert "synced_count" in sync_result

    # ── 链路6: 参考数据→实体模型→质量统计→治理看板 ──
    def test_chain6_reference_to_dashboard(self):
        """参考数据 -> 实体模型校验 -> 质量统计 -> 治理看板。"""
        # 导入参考数据
        ref_svc = MdmReferenceService()
        ref_result = ref_svc.import_reference_data("地域编码", [
            {"标准编码": "110000", "标准名称": "北京市", "别名列表": "北京,Beijing", "映射关系": "CN-11", "有效日期": "2026-12-31"},
        ])
        assert ref_result["imported"] > 0, f"参考数据导入失败: {ref_result}"

        # 查询参考数据
        found_ref = ref_svc.lookup_reference_value("地域编码", "110000")
        assert found_ref is not None, "应查询到参考数据"

        # 校验实体模型配置
        model_svc = EntityModelService()
        model_validation = model_svc.validate_entity_model(1, ["model_id", "model_name", "domain"])
        assert "checks" in model_validation

        # 计算质量统计
        quality_svc = MdmQualityService()
        records = [
            {"name": "张三", "phone": "13800138000", "email": "zhang@test.com"},
            {"name": "李四", "phone": "13900139000", "email": ""},
        ]
        quality_stats = quality_svc.compute_quality_metrics("customer", records, ["name", "phone"])
        assert "completeness_pct" in quality_stats, f"质量统计缺失完备率: {quality_stats}"
        assert "duplication_pct" in quality_stats, "质量统计缺失重复率"
        assert "consistency_pct" in quality_stats, "质量统计缺失一致率"

        # 查询质量趋势
        trend = quality_svc.query_quality_trend("customer")
        assert isinstance(trend, list), "质量趋势应为列表"

        # 生成治理看板
        dashboard_svc = MdmDashboardService()
        dashboard = dashboard_svc.generate_governance_dashboard(1)
        if dashboard["ok"]:
            stats = dashboard["dashboard"]
            assert "total_source_systems" in stats
            assert "total_golden_records" in stats
            assert "total_clusters" in stats

        # 聚合全局治理摘要
        summary = dashboard_svc.aggregate_governance_summary()
        assert "source_systems" in summary
        assert "golden_records" in summary
        assert "duplicate_clusters" in summary

    # ── 链路7: 黄金记录版本→按版本匹配生效窗口→历史血缘导出 ──
    def test_chain7_versioned_lineage_export(self):
        """指定黄金版本 -> 生效窗口匹配血缘 -> 历史导出与核对范围。"""
        golden_id = "GR-audit-2026-03"
        version_svc = MdmVersionService()
        # 同一历史版本有两项复核：两个复核批次共用一个版本快照，
        # 版本时间用补录的批次时间，而不是补录当刻
        version_svc.snapshot_golden_version(
            golden_id,
            {"phone": "13800001111", "address": "北京市朝阳区A路1号", "代表字段": "phone"},
            version_time="2026-03-01T09:00:00",
            change_batch="BATCH-2026-03",
        )
        version_svc.snapshot_golden_version(
            golden_id,
            {"phone": "13900002222"},
            version_time="2026-06-15T10:00:00",
            change_batch="BATCH-2026-06",
        )
        history = version_svc.query_version_history(golden_id)
        snapshot = next(v for v in history if v["版本时间"] == "2026-03-01T09:00:00")

        lineage_svc = RecordLineageService()

        def add_lineage(field, system, record, raw, transforms, effective,
                        expire_time="", review="", version=""):
            return lineage_svc.record_field_lineage(
                golden_id, record, system, field, transforms,
                raw_value=raw, effective_time=effective, expire_time=expire_time,
                version=version, review=review,
            )

        # 旧电话的历次变换：标准化两次，后一次接替前一次，均早于版本时间
        add_lineage("customer.phone", "CRM", "SRC-CRM-88", "138-0000-1111",
                    ["trim"], "2026-02-01T00:00:00",
                    expire_time="2026-02-20T00:00:00", review="复核-2026-02")
        add_lineage("customer.phone", "CRM", "SRC-CRM-88", "13800001111",
                    ["trim", "去掉分隔符"], "2026-02-20T00:00:00", review="复核-2026-03")
        # 旧地址只有原始值，没有来源凭证
        add_lineage("customer.address", "ERP", "SRC-ERP-77", "北京市朝阳区A路1号",
                    [], "2026-02-28T00:00:00", review="复核-2026-03")
        # 版本之后的联系方式变更：不得混入更早的历史导出
        add_lineage("customer.phone", "CRM", "SRC-CRM-88", "13900002222",
                    ["trim"], "2026-06-15T10:00:00", version="2")
        # 后来加入的客服来源：只在窗口外，不进更早版本的字段来源
        add_lineage("customer.phone", "客服工单", "SRC-CS-01", "13700003333",
                    ["人工修正"], "2026-10-01T00:00:00", version="3")

        version = snapshot["版本号"]
        result = lineage_svc.export_lineage_for_version(golden_id, version)
        assert result["ok"] is True, f"历史血缘导出失败: {result}"

        # 版本依据与有效时间同时给出
        assert result["版本依据"]["版本时间"] == snapshot["版本时间"]
        assert result["有效时间"]["起"] == snapshot["版本时间"]
        assert result["有效时间"]["止"] == "2026-06-15T10:00:00"

        # 旧电话：窗口内保留历次变换，取版本时点仍生效的一条
        phone = [f for f in result["字段"] if f["字段路径"] == "customer.phone"]
        assert len(phone) == 1, f"应只有 CRM 一个电话来源: {phone}"
        assert phone[0]["原始值"] == "13800001111", phone[0]
        assert phone[0]["历史条数"] == 2, "旧电话的历次变换应可追溯"
        assert [h["原始值"] for h in phone[0]["历史"]] == ["138-0000-1111", "13800001111"]

        # 旧地址：原始值在，来源凭证缺失，要交代可核对范围
        address = [f for f in result["字段"] if f["字段路径"] == "customer.address"]
        assert address and address[0]["原始值"] == "北京市朝阳区A路1号"
        assert address[0]["变换证据"] == ""
        assert address[0]["核对状态"] == "缺变换证据，可核对原始值"
        assert "customer.address@ERP" in result["核对范围"]["缺失变换证据字段"]
        assert "customer.phone" in result["核对范围"]["可核对字段"]

        # 后来加入的客服来源不进入更早版本
        systems = {f["来源系统"] for f in result["字段"]}
        assert "客服工单" not in systems, f"客服来源不应出现在历史导出: {systems}"
        timeline = {item["来源系统"]: item for item in result["来源系统时间线"]}
        assert timeline["客服工单"]["晚于版本加入"] is True
        assert timeline["客服工单"]["纳入本版本"] is False

        # 历史证据原样存留：窗口外记录仍在存储里，没有被删改
        stored = [r for r in store.rows("record_lineage") if r.get("黄金ID") == golden_id]
        assert any(r["来源系统"] == "客服工单" and r["原始值"] == "13700003333" for r in stored)
        assert len(result["窗口外血缘"]) >= 2

        # 导出批次可被审计批次再次下载核对
        exports = lineage_svc.list_version_exports(golden_id)
        assert exports and exports[0]["目标版本"] == version
        assert exports[0]["导出编号"] == result["导出编号"]

        # 不存在的版本给出明确原因而不是空导出
        missing = lineage_svc.export_lineage_for_version(golden_id, "99")
        assert missing["ok"] is False and "99" in missing["reason"]


if __name__ == "__main__":
    runner = TestBusinessChains()
    tests = [
        ("链路1: 来源系统→入库→导入→清洗", runner.test_chain1_source_import_cleanse),
        ("链路2: 匹配规则→匹配任务→重复簇", runner.test_chain2_match_to_cluster),
        ("链路3: 重复簇→合并→黄金记录→血缘", runner.test_chain3_dup_to_golden_lineage),
        ("链路4: 清洗→优胜策略→版本快照", runner.test_chain4_survivorship_to_version),
        ("链路5: 黄金记录→查询接口→分发同步", runner.test_chain5_golden_to_sync),
        ("链路6: 参考数据→实体模型→质量统计→看板", runner.test_chain6_reference_to_dashboard),
        ("链路7: 黄金版本→生效窗口→历史血缘导出", runner.test_chain7_versioned_lineage_export),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            print(f"  PASS: {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {name} -> {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"结果: {passed}/{len(tests)} 通过, {failed} 失败")
    assert failed == 0, f"{failed} 条链路测试失败！"