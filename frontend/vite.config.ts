import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/items': {
          target: env.VITE_API_TARGET,
          changeOrigin: true,
        },
        '/analytics': {
          target: env.VITE_API_TARGET,
          changeOrigin: true,
        },
        '/pipeline': {
          target: env.VITE_API_TARGET,
          changeOrigin: true,
        },
      },
    },
  }
})