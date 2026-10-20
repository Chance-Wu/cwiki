import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    fs: {
      allow: ['.'],
    },
    watch: {
      // 原子写工具（编辑器/代理）会在源码目录旁创建 .<name>.<pid>.<uuid>.tmpdir 临时目录，
      // Windows 上 chokidar 监听其中的 .tmp 文件会抛 EBUSY 并让 dev server 整体崩溃。
      ignored: ['**/.*.tmpdir/**', '**/*.tmp', '**/.~*', '**/node_modules/**', '**/dist/**'],
    },
    proxy: {
      '/v1': 'http://127.0.0.1:5172',
    },
  },
  // 生产预览：日常浏览用（tasks.py preview），内存占用约为 dev 模式一半
  preview: {
    host: '0.0.0.0',
    port: 4173,
    proxy: {
      '/v1': 'http://127.0.0.1:5172',
    },
  },
  build: {
    cssCodeSplit: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('react-dom') || id.includes('/react/')) {
              return 'vendor-react'
            }
            if (id.includes('react-router')) {
              return 'vendor-router'
            }
            if (id.includes('@tanstack')) {
              return 'vendor-query'
            }
            if (id.includes('react-markdown') || id.includes('mdast') || id.includes('remark')) {
              return 'vendor-markdown'
            }
            if (id.includes('lucide-react')) {
              return 'vendor-icons'
            }
            if (id.includes('framer-motion')) {
              return 'vendor-animation'
            }
            if (id.includes('react-syntax-highlighter') || id.includes('prismjs')) {
              return 'vendor-syntax'
            }
            if (id.includes('katex')) {
              return 'vendor-math'
            }
            if (id.includes('mermaid')) {
              return 'vendor-mermaid'
            }
            if (id.includes('cmdk') || id.includes('@radix-ui/react-dialog')) {
              return 'vendor-dialog'
            }
          }
        },
      },
    },
    chunkSizeWarningLimit: 500,
  },
})
