<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Download, Eye, ExternalLink, File, FileImage, FileText, Folder, FolderOpen, RefreshCw, Search } from 'lucide-vue-next'
import { ApiError } from '../../api/client'
import { openLocalPath } from '../../api/local'
import {
  artifactPreviewUrl,
  listArtifactBrowser,
  saveBrowserFileAs,
  searchArtifactBrowser,
  type ArtifactBrowserEntry,
  type ArtifactBrowserListResult,
} from '../../api/artifactBrowser'
import { useToast } from '../../composables/useToast'

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
const toast = useToast()

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

const HIDDEN_INTERNAL_FILES = new Set(['conversion-report.json', '.conversion-report.json'])

const visibleFiles = computed(() => {
  const base = currentFiles.value.filter((item) => !HIDDEN_INTERNAL_FILES.has(item.name))
  const needle = searchText.value.trim().toLowerCase()
  const files = needle
    ? base.filter((item) => `${item.name} ${item.extension || ''}`.toLowerCase().includes(needle))
    : base
  return [...files].sort((a, b) => {
    if (a.item_type !== b.item_type) return a.item_type === 'folder' ? -1 : 1
    return a.name.localeCompare(b.name, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' })
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

function canInlinePreview(row: ArtifactBrowserEntry) {
  const mime = row.media_type || ''
  return mime.startsWith('image/') || mime === 'application/pdf'
}

const previewableFiles = computed(() => visibleFiles.value.filter((row) => row.item_type === 'file' && canInlinePreview(row)))
const previewIndex = computed(() =>
  previewItem.value ? previewableFiles.value.findIndex((item) => item.relative_path === previewItem.value?.relative_path) : -1,
)
const hasPrevPreview = computed(() => previewIndex.value > 0)
const hasNextPreview = computed(() => previewIndex.value >= 0 && previewIndex.value < previewableFiles.value.length - 1)

function stepPreview(delta: number) {
  const nextIdx = previewIndex.value + delta
  if (nextIdx >= 0 && nextIdx < previewableFiles.value.length) {
    previewItem.value = previewableFiles.value[nextIdx]
  }
}

function handlePreviewKeydown(event: KeyboardEvent) {
  if (!previewVisible.value) return
  if (event.key === 'ArrowLeft' && hasPrevPreview.value) {
    event.preventDefault()
    stepPreview(-1)
  } else if (event.key === 'ArrowRight' && hasNextPreview.value) {
    event.preventDefault()
    stepPreview(1)
  }
}

watch(previewVisible, (open) => {
  if (open) {
    window.addEventListener('keydown', handlePreviewKeydown)
  } else {
    window.removeEventListener('keydown', handlePreviewKeydown)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handlePreviewKeydown)
})

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
  const d = new Date(millis)
  if (Number.isNaN(d.getTime())) return '-'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
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
  } else if (canInlinePreview(row)) {
    openPreview(row)
  } else {
    openWithSystemApp(row)
  }
}

function openPreview(row: ArtifactBrowserEntry) {
  previewItem.value = row
  previewVisible.value = true
}

async function openWithSystemApp(row: ArtifactBrowserEntry) {
  try {
    await openLocalPath(row.relative_path, {
      taskId: props.taskId,
      reveal: false,
    })
  } catch (err) {
    toast.error(err, '调用系统程序打开失败')
  }
}

async function handleSaveAs(row: ArtifactBrowserEntry) {
  try {
    const res = await saveBrowserFileAs(row.relative_path, row.name, props.taskId)
    if (res.saved) {
      toast.success(`已保存至 ${res.destination}`)
    }
  } catch (err) {
    toast.error(err, '另存为失败')
  }
}

async function handleRevealInOs(row: ArtifactBrowserEntry) {
  try {
    await openLocalPath(row.relative_path, {
      taskId: props.taskId,
      reveal: row.item_type === 'file',
    })
  } catch (err) {
    toast.error(err, '打开本地目录失败')
  }
}

function isSelected(row: ArtifactBrowserEntry) {
  return selectedRows.value.some((item) => item.relative_path === row.relative_path)
}

function toggleMobileSelection(row: ArtifactBrowserEntry, value: boolean) {
  if (row.item_type !== 'file') return
  if (value) {
    if (!isSelected(row)) selectedRows.value = [...selectedRows.value, row]
  } else {
    selectedRows.value = selectedRows.value.filter((item) => item.relative_path !== row.relative_path)
  }
  emitSelection()
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

        <div v-loading="loading" class="artifact-mobile-list">
          <button
            v-for="row in visibleFiles"
            :key="row.relative_path"
            class="artifact-mobile-card"
            type="button"
            @click="openRow(row)"
          >
            <span class="artifact-mobile-main">
              <component :is="iconFor(row)" :size="19" />
              <span>
                <strong>{{ row.name }}</strong>
                <small>{{ displayType(row) }} · {{ row.item_type === 'folder' ? '目录' : formatSize(row.size_bytes) }}</small>
              </span>
            </span>
            <span class="artifact-mobile-actions" @click.stop>
              <el-checkbox
                v-if="row.item_type === 'file'"
                :model-value="isSelected(row)"
                aria-label="选择文件"
                @change="toggleMobileSelection(row, Boolean($event))"
              />
              <el-button v-if="row.item_type === 'folder'" size="small" :icon="Folder" @click="openRow(row)">打开</el-button>
              <template v-else>
                <el-button v-if="canInlinePreview(row)" size="small" :icon="Eye" @click="openPreview(row)">预览</el-button>
                <el-button v-else size="small" :icon="ExternalLink" @click="openWithSystemApp(row)">打开</el-button>
                <el-button size="small" :icon="Download" @click="handleSaveAs(row)">另存为</el-button>
                <el-button size="small" :icon="FolderOpen" @click="handleRevealInOs(row)">位置</el-button>
              </template>
            </span>
          </button>
          <el-empty v-if="!loading && !visibleFiles.length" description="暂无文件" />
        </div>

        <el-table
          v-loading="loading"
          class="artifact-desktop-table"
          :data="visibleFiles"
          row-key="relative_path"
          height="520"
          empty-text="暂无文件"
          @selection-change="handleSelectionChange"
          @row-dblclick="openRow"
        >
          <el-table-column type="selection" width="38" :selectable="(row: ArtifactBrowserEntry) => row.item_type === 'file'" />
          <el-table-column label="名称" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <button class="artifact-name-button" type="button" @click="openRow(row)">
                <component :is="iconFor(row)" :size="17" />
                <span>{{ row.name }}</span>
              </button>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="68">
            <template #default="{ row }">{{ displayType(row) }}</template>
          </el-table-column>
          <el-table-column label="大小" width="88" class-name="mono">
            <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="更新时间" width="144" class-name="mono">
            <template #default="{ row }">{{ formatTime(row.modified_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="192" fixed="right" align="right">
            <template #default="{ row }">
              <div class="artifact-row-actions">
                <button v-if="row.item_type === 'folder'" type="button" class="artifact-action-pill is-primary" @click="openRow(row)">
                  打开目录
                </button>
                <template v-else>
                  <button
                    v-if="canInlinePreview(row)"
                    type="button"
                    class="artifact-action-pill is-primary"
                    @click="openPreview(row)"
                  >
                    预览
                  </button>
                  <button
                    v-else
                    type="button"
                    class="artifact-action-pill is-primary"
                    title="调用系统默认软件打开"
                    @click="openWithSystemApp(row)"
                  >
                    打开
                  </button>
                  <button type="button" class="artifact-action-pill" @click="handleSaveAs(row)">另存为</button>
                  <button type="button" class="artifact-action-pill" title="在系统文件夹中定位" @click="handleRevealInOs(row)">位置</button>
                </template>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <el-dialog v-model="previewVisible" class="artifact-preview-dialog" width="84vw" top="4vh" append-to-body>
      <template #header>
        <div class="artifact-preview-header">
          <div class="artifact-preview-title-wrap">
            <span class="artifact-preview-title">{{ previewItem?.name }}</span>
            <small v-if="previewIndex >= 0 && previewableFiles.length > 1" class="artifact-preview-counter mono">
              {{ previewIndex + 1 }} / {{ previewableFiles.length }}
            </small>
          </div>
          <div v-if="previewItem" class="artifact-preview-toolbar">
            <template v-if="previewableFiles.length > 1">
              <button
                type="button"
                class="artifact-action-pill"
                :disabled="!hasPrevPreview"
                title="上一项 (←)"
                @click="stepPreview(-1)"
              >
                <ChevronLeft :size="14" />上一项
              </button>
              <button
                type="button"
                class="artifact-action-pill"
                :disabled="!hasNextPreview"
                title="下一项 (→)"
                @click="stepPreview(1)"
              >
                下一项<ChevronRight :size="14" />
              </button>
            </template>
            <button type="button" class="artifact-action-pill" @click="handleSaveAs(previewItem)">另存为</button>
            <button type="button" class="artifact-action-pill" @click="handleRevealInOs(previewItem)">位置</button>
          </div>
        </div>
      </template>
      <div v-if="previewItem && canPreview" class="artifact-preview-frame">
        <img v-if="previewMime.startsWith('image/')" :src="previewUrl" :alt="previewItem.name" />
        <iframe v-else :src="previewUrl" title="文件预览" />
      </div>
      <el-empty v-else description="正在使用系统软件打开或另存文件">
        <el-button v-if="previewItem" type="primary" :icon="ExternalLink" @click="openWithSystemApp(previewItem)">用系统软件打开</el-button>
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
  grid-template-columns: minmax(168px, 204px) minmax(0, 1fr);
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

.artifact-tree-node svg,
.artifact-name-button svg {
  flex: 0 0 auto;
}

.artifact-tree-node span,
.artifact-name-button span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.artifact-row-actions {
  display: inline-flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  white-space: nowrap;
}

.artifact-action-pill {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 26px;
  padding: 0 9px;
  border-radius: 6px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(30, 42, 68, 0.55);
  color: var(--app-muted);
  font-size: 12px;
  font-weight: 500;
  line-height: 24px;
  cursor: pointer;
  white-space: nowrap;
  transition: color 140ms ease, background-color 140ms ease, border-color 140ms ease;
}

.artifact-action-pill:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.artifact-action-pill:hover {
  color: var(--app-text);
  background: rgba(51, 65, 95, 0.85);
  border-color: rgba(148, 163, 184, 0.34);
}

.artifact-action-pill.is-primary {
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.14);
  border-color: rgba(129, 140, 248, 0.28);
}

.artifact-action-pill.is-primary:hover {
  color: #ffffff;
  background: rgba(99, 102, 241, 0.32);
  border-color: rgba(129, 140, 248, 0.55);
}

.artifact-content-panel {
  min-width: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.artifact-mobile-list {
  display: none;
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

.artifact-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-right: 28px;
  min-width: 0;
}

.artifact-preview-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.artifact-preview-title {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}

.artifact-preview-counter {
  flex: 0 0 auto;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.16);
  color: #a5b4fc;
  font-size: 12px;
}

.artifact-preview-toolbar {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
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
  .artifact-browser-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .artifact-browser-title {
    min-width: 0;
    flex-wrap: wrap;
  }

  .artifact-browser-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .artifact-search {
    grid-column: 1 / -1;
    width: 100%;
  }

  .artifact-browser-actions :deep(.el-button) {
    min-height: 40px;
    margin-left: 0;
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

@media (max-width: 760px) {
  .artifact-browser-layout {
    min-height: 0;
  }

  .artifact-tree-panel {
    max-height: 156px;
  }

  .artifact-breadcrumb {
    min-height: 36px;
    padding: 6px 8px;
  }

  .artifact-browser-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .artifact-search {
    grid-column: 1 / -1;
  }

  .artifact-content-panel :deep(.el-table) {
    height: 420px !important;
  }

  .artifact-desktop-table {
    display: none;
  }

  .artifact-mobile-list {
    min-height: 240px;
    max-height: 48dvh;
    display: grid;
    align-content: start;
    gap: 8px;
    overflow: auto;
    padding: 8px;
  }

  .artifact-mobile-card {
    width: 100%;
    display: grid;
    gap: 10px;
    padding: 10px;
    border: 1px solid var(--app-border);
    border-radius: 8px;
    background: var(--app-bg-2);
    color: var(--app-text);
    text-align: left;
  }

  .artifact-mobile-main {
    min-width: 0;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 9px;
    align-items: start;
  }

  .artifact-mobile-main svg {
    margin-top: 2px;
    color: var(--app-primary);
  }

  .artifact-mobile-main strong,
  .artifact-mobile-main small {
    display: block;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .artifact-mobile-main strong {
    font-size: 14px;
    line-height: 1.35;
  }

  .artifact-mobile-main small {
    margin-top: 2px;
    color: var(--app-muted);
    font-size: 12px;
  }

  .artifact-mobile-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    min-width: 0;
  }

  .artifact-mobile-actions :deep(.el-button) {
    margin-left: 0;
  }

  .artifact-preview-frame {
    height: 68dvh;
  }
}
</style>
