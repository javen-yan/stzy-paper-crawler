<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppHeader from '../components/layout/AppHeader.vue'
</script>

<template>
  <div class="app-shell">
    <AppHeader />
    <main class="workspace" tabindex="-1">
      <RouterView />
    </main>
  </div>
</template>
