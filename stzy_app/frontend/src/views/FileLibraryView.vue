<script setup lang="ts">
import FileTable from '../components/files/FileTable.vue'
</script>

<template>
  <div class="page-stack">
    <section class="page-hero">
      <div>
        <p class="eyebrow">浏览已下载文件</p>
        <h2>文件库</h2>
      </div>
    </section>

    <el-card shadow="never">
      <template #header>
        <div class="card-header file-library-header">
          <span>文件列表</span>
          <small class="block-muted">按任务筛选名称与实际保存路径浏览。</small>
        </div>
      </template>
      <FileTable />
    </el-card>
  </div>
</template>

<style scoped>
.file-library-header {
  align-items: flex-start;
}

.file-library-header small {
  min-width: 0;
}

@media (max-width: 760px) {
  .file-library-header {
    display: grid;
    gap: 4px;
  }
}
</style>
