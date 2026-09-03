<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from './composables/useAuth'
import { useRuntime } from './composables/useRuntime'

const router = useRouter()
const { authenticated, initialize } = useAuth()
const { runtime, loadRuntime } = useRuntime()

onMounted(async () => {
  const loadedRuntime = await loadRuntime()
  const session = await initialize(loadedRuntime.mode)
  if (!session.authenticated && router.currentRoute.value.path !== '/login') {
    await router.replace('/login')
  } else if (session.authenticated && router.currentRoute.value.path === '/') {
    await router.replace('/tasks')
  }
})
</script>

<template>
  <router-view v-if="runtime && (authenticated || $route.path === '/login')" />
  <div v-else class="boot-screen">
    <el-card shadow="never">
      <el-skeleton :rows="3" animated />
    </el-card>
  </div>
</template>
