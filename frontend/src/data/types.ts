/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

export type VersionLineageField = {
  字段路径: string
  来源系统: string
  来源记录: string
  原始值: string
  变换证据: string
  取值时间: string
  生效时间: string
  失效时间: string
  血缘编号: string
  核对状态: string
  历史条数: number
  历史: Record<string, string>[]
}

export type VersionLineageExport = {
  导出编号: string
  黄金ID: string
  目标版本: string
  版本依据: {
    版本编号: string
    版本号: string
    版本时间: string
    变更字段: string
    变更批次: string
  }
  有效时间: { 起: string; 止: string }
  字段: VersionLineageField[]
  核对范围: {
    可核对字段: string[]
    缺失原始值字段: string[]
    缺失变换证据字段: string[]
    缺失来源字段: string[]
    说明: string
  }
  来源系统时间线: {
    来源系统: string
    最早生效时间: string
    纳入本版本: boolean
    晚于版本加入: boolean
  }[]
  窗口外血缘: Record<string, string>[]
  历史证据: { 保留方式: string; 纳入条数: number; 窗口外条数: number }
}
