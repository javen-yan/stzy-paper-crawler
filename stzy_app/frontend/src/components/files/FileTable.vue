<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { Download, Eye, File, FileImage, FileText, Folder, RefreshCw, Search } from 'lucide-vue-next'
import { ApiError } from '../../api/client'
import {
  artifactDownloadUrl,
  artifactPreviewUrl,
  listArtifactBrowser,
  searchArtifactBrowser,
  type ArtifactBrowserEntry,
  type ArtifactBrowserListResult,
} from '../../api/artifactBrowser'

type TreeNode = {
  id: string
  label: string
  path: string
  children: TreeNode[]
}

const props = defineProps<{ taskId?: string }>()
const emit = defineEmits<{
  selectionChange: [filePaths: string[]]
}>()

const ROOT_PATH = ''
const ROOT_LABEL = '全部文件'

const loading = ref(false)
const error = ref('')
const currentPath = ref(ROOT_PATH)
const currentFiles = ref<ArtifactBrowserEntry[]>([])
const selectedRows = ref<ArtifactBrowserEntry[]>([])
const searchText = ref('')
const previewVisible = ref(false)
const previewItem = ref<ArtifactBrowserEntry | null>(null)
const expandedKeys = ref<string[]>([ROOT_PATH])
const treeRef = ref()
const treeData = ref<TreeNode[]>([{ id: ROOT_PATH, label: ROOT_LABEL, path: ROOT_PATH, children: [] }])
const loadedDirs = new Set<string>()
const nodeMap = new Map<string, TreeNode>([[ROOT_PATH, treeData.value[0]]])

const visibleFiles = computed(() => {
  const needle = searchText.value.trim().toLowerCase()
  const files = needle
    ? currentFiles.value.filter((item) => `${item.name} ${item.extension || ''}`.toLowerCase().includes(needle))
    : currentFiles.value
  return [...files].sort((a, b) => {
    if (a.item_type !== b.item_type) return a.item_type === 'folder' ? -1 : 1
    return a.name.localeCompare(b.name, 'zh-Hans-CN')
  })
})

const breadcrumb = computed(() => {
  const parts = currentPath.value ? currentPath.value.split('/').filter(Boolean) : []
  const crumbs = [{ label: ROOT_LABEL, path: ROOT_PATH }]
  let path = ''
  for (const part of parts) {
    path = path ? `${path}/${part}` : part
    crumbs.push({ label: part, path })
  }
  return crumbs
})

const selectedCount = computed(() => selectedRows.value.length)
const previewUrl = computed(() => (previewItem.value ? artifactPreviewUrl(previewItem.value.relative_path, props.taskId) : ''))
const previewMime = computed(() => previewItem.value?.media_type || '')
const canPreview = computed(() => previewMime.value.startsWith('image/') || previewMime.value === 'application/pdf')

function iconFor(row: ArtifactBrowserEntry) {
  if (row.item_type === 'folder') return Folder
  if (row.media_type === 'application/pdf') return FileText
  if ((row.media_type || '').startsWith('image/')) return FileImage
  return File
}

function displayType(row: ArtifactBrowserEntry) {
  if (row.item_type === 'folder') return '目录'
  if (row.media_type === 'application/pdf') return 'PDF'
  if ((row.media_type || '').startsWith('image/')) return '图片'
  return row.extension ? row.extension.toUpperCase() : '文件'
}

function formatSize(value?: number | null) {
  if (!value) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(value?: number | null) {
  if (!value) return '-'
  const millis = value > 10_000_000_000 ? value : value * 1000
  return new Date(millis).toLocaleString()
}

function ensureTreeNode(path: string, label: string, parentPath = ROOT_PATH) {
  const existing = nodeMap.get(path)
  if (existing) return existing
  const parent = nodeMap.get(parentPath) || treeData.value[0]
  const node = { id: path, label, path, children: [] }
  parent.children.push(node)
  parent.children.sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))
  nodeMap.set(path, node)
  return node
}

function updateTree(path: string, files: ArtifactBrowserEntry[]) {
  const parent = nodeMap.get(path) || ensureTreeNode(path, path || ROOT_LABEL)
  const folders = files.filter((item) => item.item_type === 'folder')
  parent.children = folders
    .map((item) => ensureTreeNode(item.relative_path, item.name, path))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))
  loadedDirs.add(path)
}

function emitSelection() {
  emit(
    'selectionChange',
    selectedRows.value.map((item) => item.relative_path).filter(Boolean),
  )
}

async function loadDirectory(path = ROOT_PATH, options: { force?: boolean } = {}) {
  if (!options.force && currentPath.value === path && loadedDirs.has(path)) return
  loading.value = true
  error.value = ''
  try {
    const payload: ArtifactBrowserListResult = await listArtifactBrowser({ path, task_id: props.taskId })
    currentPath.value = payload.current_path
    currentFiles.value = payload.items
    selectedRows.value = []
    emitSelection()
    updateTree(payload.current_path, payload.items)
    expandedKeys.value = Array.from(new Set([...expandedKeys.value, ...breadcrumb.value.map((item) => item.path)]))
    await nextTick()
    treeRef.value?.setCurrentKey(payload.current_path)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '文件列表加载失败'
  } finally {
    loading.value = false
  }
}

async function runDeepSearch() {
  const filter = searchText.value.trim()
  if (!filter) {
    await loadDirectory(currentPath.value, { force: true })
    return
  }
  loading.value = true
  error.value = ''
  try {
    const payload = await searchArtifactBrowser({ path: currentPath.value, task_id: props.taskId, filter, deep: true })
    currentFiles.value = payload.items
    selectedRows.value = []
    emitSelection()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '搜索失败'
  } finally {
    loading.value = false
  }
}

function openRow(row: ArtifactBrowserEntry) {
  if (row.item_type === 'folder') {
    loadDirectory(row.relative_path)
  } else {
    openPreview(row)
  }
}

function openPreview(row: ArtifactBrowserEntry) {
  previewItem.value = row
  previewVisible.value = true
}

function handleSelectionChange(rows: ArtifactBrowserEntry[]) {
  selectedRows.value = rows.filter((row) => row.item_type === 'file')
  emitSelection()
}

onMounted(() => {
  loadDirectory(ROOT_PATH, { force: true })
})
</script>

<template>
  <div class="artifact-browser">
    <div class="artifact-browser-toolbar">
      <div class="artifact-browser-title">
        <span>{{ taskId ? '当前任务文件' : '全部任务文件' }}</span>
        <small v-if="selectedCount">已选 {{ selectedCount }} 个文件</small>
      </div>
      <div class="artifact-browser-actions">
        <el-input
          v-model="searchText"
          clearable
          class="artifact-search"
          placeholder="搜索当前目录"
          :prefix-icon="Search"
          @keyup.enter="runDeepSearch"
          @clear="loadDirectory(currentPath, { force: true })"
        />
        <el-button :icon="Search" :loading="loading" @click="runDeepSearch">全文搜索</el-button>
        <el-button :icon="RefreshCw" :loading="loading" @click="loadDirectory(currentPath, { force: true })">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="error" class="artifact-error" type="error" :title="error" show-icon :closable="false" />

    <div class="artifact-browser-layout">
      <aside class="artifact-tree-panel">
        <el-tree
          ref="treeRef"
          node-key="path"
          :data="treeData"
          :props="{ label: 'label', children: 'children' }"
          :default-expanded-keys="expandedKeys"
          :current-node-key="currentPath"
          highlight-current
          @node-click="(node: TreeNode) => loadDirectory(node.path)"
        >
          <template #default="{ node }">
            <span class="artifact-tree-node">
              <Folder :size="16" />
              <span>{{ node.label }}</span>
            </span>
          </template>
        </el-tree>
      </aside>

      <section class="artifact-content-panel">
        <div class="artifact-breadcrumb">
          <button
            v-for="crumb in breadcrumb"
            :key="crumb.path"
            class="artifact-crumb"
            type="button"
            @click="loadDirectory(crumb.path)"
          >
            {{ crumb.label }}
          </button>
        </div>

        <el-table
          v-loading="loading"
          :data="visibleFiles"
          row-key="relative_path"
          height="520"
          empty-text="暂无文件"
          @selection-change="handleSelectionChange"
          @row-dblclick="openRow"
        >
          <el-table-column type="selection" width="42" :selectable="(row: ArtifactBrowserEntry) => row.item_type === 'file'" />
          <el-table-column label="名称" min-width="320" show-overflow-tooltip>
            <template #default="{ row }">
              <button class="artifact-name-button" type="button" @click="openRow(row)">
                <component :is="iconFor(row)" :size="18" />
                <span>{{ row.name }}</span>
              </button>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ displayType(row) }}</template>
          </el-table-column>
          <el-table-column label="大小" width="110">
            <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="更新时间" width="190">
            <template #default="{ row }">{{ formatTime(row.modified_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="176" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.item_type === 'folder'" size="small" :icon="Folder" @click="openRow(row)">打开</el-button>
              <template v-else>
                <el-button size="small" :icon="Eye" @click="openPreview(row)">预览</el-button>
                <el-button size="small" :icon="Download" tag="a" :href="artifactDownloadUrl(row.relative_path, taskId)">下载</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <el-dialog v-model="previewVisible" class="artifact-preview-dialog" width="82vw" top="5vh" append-to-body>
      <template #header>
        <span class="artifact-preview-title">{{ previewItem?.name }}</span>
      </template>
      <div v-if="previewItem && canPreview" class="artifact-preview-frame">
        <img v-if="previewMime.startsWith('image/')" :src="previewUrl" :alt="previewItem.name" />
        <iframe v-else :src="previewUrl" title="文件预览" />
      </div>
      <el-empty v-else description="该文件不支持在线预览">
        <el-button v-if="previewItem" type="primary" :icon="Download" tag="a" :href="artifactDownloadUrl(previewItem.relative_path, taskId)">下载文件</el-button>
      </el-empty>
    </el-dialog>
  </div>
</template>

<style scoped>
.artifact-browser {
  display: grid;
  gap: 12px;
}

.artifact-browser-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.artifact-browser-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 180px;
  color: var(--app-text);
  font-weight: 600;
}

.artifact-browser-title small {
  font-weight: 400;
}

.artifact-browser-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.artifact-search {
  width: 260px;
}

.artifact-browser-layout {
  min-height: 560px;
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--app-surface);
}

.artifact-tree-panel {
  min-width: 0;
  padding: 10px;
  border-right: 1px solid var(--app-border);
  background: var(--app-bg-2);
  overflow: auto;
}

.artifact-tree-panel :deep(.el-tree) {
  background: transparent;
}

.artifact-tree-node,
.artifact-name-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.artifact-tree-node span,
.artifact-name-button span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.artifact-content-panel {
  min-width: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.artifact-breadcrumb {
  min-height: 42px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--app-border);
  overflow-x: auto;
}

.artifact-crumb {
  min-height: 28px;
  border: 0;
  border-radius: 6px;
  color: var(--app-muted);
  background: transparent;
  padding: 4px 8px;
  cursor: pointer;
  white-space: nowrap;
}

.artifact-crumb:not(:last-child)::after {
  content: "/";
  margin-left: 10px;
  color: var(--app-faint);
}

.artifact-crumb:hover {
  color: var(--app-primary);
  background: var(--app-primary-soft);
}

.artifact-name-button {
  max-width: 100%;
  min-height: 34px;
  padding: 0;
  border: 0;
  color: var(--app-text);
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.artifact-name-button:hover {
  color: var(--app-primary);
}

.artifact-error {
  margin-bottom: 2px;
}

.artifact-preview-title {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.artifact-preview-frame {
  height: 76vh;
  display: grid;
  place-items: center;
  background: var(--app-bg);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  overflow: hidden;
}

.artifact-preview-frame img,
.artifact-preview-frame iframe {
  width: 100%;
  height: 100%;
  border: 0;
}

.artifact-preview-frame img {
  object-fit: contain;
}

@media (max-width: 900px) {
  .artifact-browser-toolbar,
  .artifact-browser-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .artifact-search {
    width: 100%;
  }

  .artifact-browser-layout {
    grid-template-columns: 1fr;
  }

  .artifact-tree-panel {
    max-height: 220px;
    border-right: 0;
    border-bottom: 1px solid var(--app-border);
  }
}
</style>
