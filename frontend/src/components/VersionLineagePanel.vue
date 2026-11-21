<template>
  <section class="version-export" data-testid="version-lineage-export">
    <header class="version-export-head">
      <div>
        <h3>按黄金版本回溯血缘</h3>
        <p class="page-desc">
          输入黄金ID与目标版本号，先看该版本的有效时间与可核对范围，再下载历史血缘导出文件。
        </p>
      </div>
    </header>

    <form class="analysis-form" @submit.prevent="preview">
      <label>
        <span>黄金ID</span>
        <input v-model="goldenId" data-testid="lineage-golden-id" placeholder="例如 GR-customer-0001" />
      </label>
      <label>
        <span>目标版本</span>
        <input v-model="version" data-testid="lineage-version" placeholder="例如 1" />
      </label>
      <button class="btn primary" data-testid="lineage-preview" type="submit" :disabled="loading">
        {{ loading ? '读取中…' : '查看核对范围' }}
      </button>
      <button class="btn" data-testid="lineage-download" type="button" :disabled="!payload" @click="download">
        下载历史血缘导出
      </button>
    </form>

    <p v-if="errorMessage" class="error-text" data-testid="lineage-error">{{ errorMessage }}</p>

    <template v-if="payload">
      <div class="analysis-summary">
        <article class="analysis-card">
          <span class="stat-label">目标版本</span>
          <strong class="stat-value">{{ payload.目标版本 }}</strong>
        </article>
        <article class="analysis-card">
          <span class="stat-label">版本时间</span>
          <strong class="stat-value small">{{ payload.版本依据.版本时间 }}</strong>
        </article>
        <article class="analysis-card">
          <span class="stat-label">有效时间止</span>
          <strong class="stat-value small">{{ payload.有效时间.止 || '持续有效' }}</strong>
        </article>
        <article class="analysis-card">
          <span class="stat-label">可核对字段</span>
          <strong class="stat-value">{{ payload.核对范围.可核对字段.length }}</strong>
        </article>
      </div>

      <p class="scope-note" data-testid="lineage-scope-note">{{ payload.核对范围.说明 }}</p>

      <table class="data-table">
        <thead>
          <tr>
            <th>字段路径</th>
            <th>来源系统</th>
            <th>来源记录</th>
            <th>原始值</th>
            <th>变换证据</th>
            <th>取值时间</th>
            <th>历次条数</th>
            <th>核对状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="field in payload.字段" :key="`${field.字段路径}-${field.来源系统}`">
            <td>{{ field.字段路径 }}</td>
            <td>{{ field.来源系统 }}</td>
            <td>{{ field.来源记录 || '—' }}</td>
            <td>{{ field.原始值 || '—' }}</td>
            <td>{{ field.变换证据 || '—' }}</td>
            <td>{{ field.取值时间 || '—' }}</td>
            <td>{{ field.历史条数 }}</td>
            <td :data-status="field.核对状态">{{ field.核对状态 }}</td>
          </tr>
          <tr v-if="!payload.字段.length">
            <td :colspan="8" class="empty-state">该版本窗口内没有可导出的血缘记录</td>
          </tr>
        </tbody>
      </table>

      <h4>来源系统时间线</h4>
      <p class="page-desc">用于确认后来加入的来源没有出现在更早版本的导出里。</p>
      <p class="status-legend">
        <span v-for="item in payload.来源系统时间线" :key="item.来源系统" class="legend-item">
          {{ item.来源系统 }}：{{ item.最早生效时间 }}
          <template v-if="item.纳入本版本">（纳入）</template>
          <template v-else-if="item.晚于版本加入">（晚于版本加入，未纳入）</template>
        </span>
      </p>

      <p class="page-desc">
        窗口外血缘 {{ payload.窗口外血缘.length }} 条，历史证据按原样存留，不纳入本次导出。
      </p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { downloadVersionLineage, previewVersionLineage } from '@/api/backend-service'
import type { VersionLineageExport } from '@/data/types'

const goldenId = ref('')
const version = ref('')
const payload = ref<VersionLineageExport | null>(null)
const errorMessage = ref('')
const loading = ref(false)

async function preview() {
  errorMessage.value = ''
  payload.value = null
  if (!goldenId.value.trim() || !version.value.trim()) {
    errorMessage.value = '请先填写黄金ID与目标版本'
    return
  }
  loading.value = true
  try {
    payload.value = await previewVersionLineage(goldenId.value.trim(), version.value.trim())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '历史血缘读取失败'
  } finally {
    loading.value = false
  }
}

async function download() {
  errorMessage.value = ''
  try {
    await downloadVersionLineage(goldenId.value.trim(), version.value.trim())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '历史血缘导出失败'
  }
}
</script>
