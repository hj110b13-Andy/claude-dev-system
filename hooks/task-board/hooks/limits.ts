/**
 * 看板的用量門檻與標線：讀 dispatch-config.json（單一來源，與 usage_guard.py 同一份）。
 * 讀取順序由 register.tsx 決定（專案 .claude/ → 全域 claude-dev-system/config/ → 預設）；這裡只負責解析。
 * 方案若有 until 日期，到期日（含）起改用 plan.after 的門檻（與 usage_guard.py 的 pick_thresholds 同規則）。
 */
export type BoardLimits = { fiveHour: number; sevenDay: number; markFive: number; markSeven: number; source: string }

export const DEFAULT_LIMITS: BoardLimits = { fiveHour: 80, sevenDay: 97, markFive: 80, markSeven: 97, source: '內建預設' }

type Cfg = {
  plan?: Record<string, unknown> & { current?: string; after?: string }
  usageThresholdPct?: Record<string, { fiveHour?: number; sevenDay?: number }>
  boardMeterMarks?: { fiveHour?: number; sevenDay?: number }
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** 解析設定檔文字；格式不對回 undefined（呼叫端換下一份）。today 為 YYYY-MM-DD。 */
export function parseLimits(text: string, today: string, source = ''): BoardLimits | undefined {
  let cfg: Cfg
  try {
    cfg = JSON.parse(text) as Cfg
  } catch {
    return undefined
  }
  const plan = cfg.plan ?? {}
  let cur = plan.current
  const curPlan = cur ? (plan[cur] as { until?: string } | undefined) : undefined
  if (curPlan?.until && today >= curPlan.until && plan.after) cur = plan.after
  const t = cur ? cfg.usageThresholdPct?.[cur] : undefined
  if (!t || !isNum(t.fiveHour) || !isNum(t.sevenDay)) return undefined
  const m = cfg.boardMeterMarks ?? {}
  return {
    fiveHour: t.fiveHour,
    sevenDay: t.sevenDay,
    markFive: isNum(m.fiveHour) ? m.fiveHour : DEFAULT_LIMITS.markFive,
    markSeven: isNum(m.sevenDay) ? m.sevenDay : DEFAULT_LIMITS.markSeven,
    source,
  }
}

/** 依序嘗試多份設定檔文字（已讀好的 [來源, 文字] 清單），第一份可解析者為準；都沒有回預設。 */
export function chooseLimits(files: Array<[string, string | undefined]>, today: string): BoardLimits {
  for (const [src, txt] of files) {
    if (!txt) continue
    const r = parseLimits(txt, today, src)
    if (r) return r
  }
  return DEFAULT_LIMITS
}
