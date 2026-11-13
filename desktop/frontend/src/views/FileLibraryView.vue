<script setup lang="ts">
import { FolderOutput } from 'lucide-vue-next'
import { openLocalPath } from '../api/local'
import FileTable from '../components/files/FileTable.vue'
import { useToast } from '../composables/useToast'

const toast = useToast()

async function openRootFolder() {
  try {
    await openLocalPath('')
  } catch (error) {
    toast.error(error, '打开下载目录失败')
  }
}
</script>

<template>
  <div class="page-stack">
    <section class="page-hero">
      <div>
        <h2>本地文件</h2>
        <p class="hero-subtitle">浏览已下载的试卷 PDF 与图片，点击文件可直接预览。</p>
      </div>
      <div class="hero-actions">
        <el-button @click="openRootFolder">
          <FolderOutput :size="15" style="margin-right: 6px" />在系统文件夹中打开
        </el-button>
      </div>
    </section>

    <el-card shadow="never">
      <FileTable />
    </el-card>
  </div>
</template>
