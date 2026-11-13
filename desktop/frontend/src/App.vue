<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useRuntime } from './composables/useRuntime'
import { useTasks } from './composables/useTasks'

const router = useRouter()
const { runtime, loadRuntime } = useRuntime()
const { bindRealtimeEvents } = useTasks()
const bootError = ref('')

onMounted(async () => {
  try {
    await loadRuntime()
    await bindRealtimeEvents()
    if (router.currentRoute.value.path === '/' || router.currentRoute.value.path === '/login') {
      await router.replace('/tasks')
    }
  } catch (err) {
    bootError.value = err instanceof Error ? err.message : String(err)
  }
})
</script>

<template>
  <router-view v-if="runtime" />
  <div v-else class="boot-screen">
    <el-card shadow="never">
      <el-alert v-if="bootError" type="error" :title="bootError" show-icon :closable="false" />
      <el-skeleton v-else :rows="3" animated />
    </el-card>
  </div>
</template>
