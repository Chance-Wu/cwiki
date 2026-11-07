# apps/web — Web 控制台

React 18 + TypeScript + Vite 的个人知识工作台。UI 基础组件基于 Radix UI，样式用 Tailwind，动效用 Framer Motion，服务端状态用 TanStack Query。

## 启动

```bash
python tasks.py web       # 开发服务器 :5173
python tasks.py preview   # 构建后以 :4173 启动（日常浏览，内存约为 dev 一半）
python tasks.py start     # 前后端一起启动
```

开发模式 API 默认直连 `http://127.0.0.1:5172/v1`（可用 `VITE_API_BASE` 覆盖）；构建/预览走相对 `/v1`，由 Vite preview 代理到后端。服务端启用 `app.auth_token` 后，在浏览器控制台执行 `localStorage.setItem('cwiki_auth_token', '<token>')`。

## 页面

| 路由 | 页面 | 内容 |
|------|------|------|
| `/` | `HomePage` | 今日记忆活动、健康告警、进化与学习面板、本周回顾 |
| `/pending` | `InboxPage` | 待审候选、冲突处理、批量审核 |
| `/notes` | `NotesPage` | 会话笔记与待整理内容 |
| `/memories` | `MemoriesPage` | 记忆库：混合检索、筛选、批量操作、合并 |
| `/skills` | `SkillsPage` | Skill 扫描、导入、发布 |
| `/review` | `ReviewPage` | 间隔重复复习会话与统计 |
| `/config` | `ConfigPage` | 写入决策、写入策略等行为参数 |
| `/settings` | `SettingsPage` | 偏好、数据同步、运行时与一致性运维 |
| `/graph` | `GraphPage` | 知识图谱 |
| `/quality` | `QualityPage` | 记忆质量分布与下钻 |
| `*` | `NotFoundPage` | 兜底页 |

页面通过 `App.tsx` 懒加载，外层提供 ErrorBoundary、Toast、命令面板与页面过渡。

## 目录

- `src/components/`：按域分组 —— `ui/` 基础组件，`home/`、`inbox/`、`memories/`、`memory/`、`notes/`、`review/`、`settings/`、`skills/`、`config/`、`quality/` 业务组件，以及 `Layout`、`CommandPalette`、`Toast`、`ErrorBoundary`
- `src/hooks/`：`useMemories`、`useCandidates`、`useSearch`、`useReview`、`useSkills`、`useDashboard` 等数据与交互 hooks
- `src/lib/api/`：按域拆分的 API 客户端；`base.ts` 定义 `API_BASE`、Bearer 头与统一错误处理
- `src/i18n/`：中英文案（`locales/zh.ts`、`en.ts`）与 `I18nProvider`
- `src/theme/`：亮暗主题与品牌 token
- `src/test/`：Vitest + Testing Library 用例

## 命令（在 `apps/web/` 下）

```bash
npm run dev         # Vite 开发服务器
npm run build       # tsc + vite build
npm run preview     # 预览构建产物
npm run test:run    # 单次运行 Vitest
npm run lint        # ESLint
npm run format:check
```
