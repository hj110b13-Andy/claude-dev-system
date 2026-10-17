export type BoardTask = {
  id: string
  description: string
  model: string
  startedAt: number
  /** 派工指示裡的「總時限 N 分鐘」 */
  limitMin?: number
  lastMsg?: string
  lastMsgAt?: number
  /** agent 最近一次回報的「預計還需 N 分鐘」 */
  etaMin?: number
  etaAt?: number
  /** agent 回報的「進度 已完成/總數」：最新一次與第一次（算實際速度用） */
  progDone?: number
  progTotal?: number
  progAt?: number
  prog0Done?: number
  prog0At?: number
  /** 累計 token（input＋output＋cache 寫入；cache 讀取另記） */
  tokens: number
  cacheRead: number
  endedAt?: number
  /** 結束時的狀態（completed／failed／killed），留到 5 小時窗口結束 */
  finalStatus?: string
  /** 看板啟動前就派出（沒有開始時間與 token） */
  preBoard?: boolean
  /** 任務開始／結束時的 5 小時用量 %（占比＝差值） */
  fiveStart?: number
  fiveEnd?: number
}

export type BoardUsage = {
  five?: number
  fiveResetsAt?: string
  seven?: number
  sevenResetsAt?: string
  at: number
}

export type BoardGit = { dirty: number; last: string; at: number; commits?: string[] }

declare module 'claude-code' {
  interface PluginState {
    'task-board': {
      tasks: Record<string, BoardTask>
      usage: BoardUsage
      git: BoardGit
      mainTokens: number
      usageHist: Array<[number, number]>
      currentMain: string
    }
  }
}
