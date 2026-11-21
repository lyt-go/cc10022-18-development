"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。

record_lineage 另有一条按黄金版本导出的专项路由，必须排在通用资源路由之前注册，
否则 /api/record_lineage/version-export 会被 /api/{module}/{entry_id} 抢先匹配。
"""
from __future__ import annotations

from app.routers import lineage, resource

ROUTERS = [lineage, resource]
