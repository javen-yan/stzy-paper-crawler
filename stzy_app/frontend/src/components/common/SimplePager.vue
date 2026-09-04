<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    page: number
    pageSize: number
    itemCount: number
    hasNext: boolean
    loading?: boolean
    pageSizes?: number[]
    label?: string
  }>(),
  {
    loading: false,
    pageSizes: () => [20, 50, 100],
    label: '当前页',
  },
)

const hasPrev = computed(() => props.page > 1)
const hasAnyPagerControl = computed(() => hasPrev.value || props.hasNext || props.itemCount > props.pageSize)

const emit = defineEmits<{
  prev: []
  next: []
  refresh: []
  pageSizeChange: [value: number]
}>()
</script>

<template>
  <div class="simple-pager">
    <span class="simple-pager-info">
      {{ label }}：第 {{ page }} 页，{{ itemCount }} 条
    </span>
    <div class="simple-pager-actions">
      <span class="simple-pager-size-label">每页</span>
      <el-select :model-value="pageSize" size="small" class="simple-pager-size" @change="emit('pageSizeChange', Number($event))">
        <el-option v-for="size in pageSizes" :key="size" :label="`${size} 条`" :value="size" />
      </el-select>
      <el-button v-if="hasPrev" size="small" :disabled="loading" @click="emit('prev')">上一页</el-button>
      <el-button v-if="hasNext" size="small" type="primary" plain :disabled="loading" @click="emit('next')">下一页</el-button>
      <span v-if="!hasAnyPagerControl" class="simple-pager-single">没有更多页</span>
      <el-button size="small" :loading="loading" @click="emit('refresh')">刷新</el-button>
    </div>
  </div>
</template>
