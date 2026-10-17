import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { BoardGit, BoardLimits, BoardTask, BoardUsage } from '../types'
import { chooseLimits, DEFAULT_LIMITS } from './limits'

/**
 * 任務看板（2026-10-11 使用者要求）：同時看所有任務的狀況、進度、預計還需多久、
 * 每個任務花的 token 與約佔 5 小時用量幾 %，以及 5 小時／7 天額度。
 * 額度提醒＋自動收尾仍由 ~/.claude/tools/usage_guard.py（hook）負責；這裡只負責「給人看」。
 */
const PANE = 'task-board'
const tasks = atom({ plugin: 'task-board', key: 'tasks' } as const, {})
const usage = atom({ plugin: 'task-board', key: 'usage' } as const, { at: 0 })
const git = atom({ plugin: 'task-board', key: 'git' } as const, { dirty: 0, last: '', at: 0 })
const mainTokens = atom({ plugin: 'task-board', key: 'mainTokens' } as const, 0)
/** 目前這則使用者訊息對應的主對話任務 id（2026-10-11 使用者：我自己在主對話做的事也要顯示在執行中） */
const currentMain = atom({ plugin: 'task-board', key: 'currentMain' } as const, '')
/** 5 小時用量取樣 [毫秒, %]（每 30 秒），用來算每筆 commit 期間花掉多少額度 */
const usageHist = atom({ plugin: 'task-board', key: 'usageHist' } as const, [] as Array<[number, number]>)

/** 用量門檻與標線（讀 dispatch-config.json；refreshUsage 每輪更新）。預設 80／97。 */
const limitsAtom = atom({ plugin: 'task-board', key: 'limits' } as const, DEFAULT_LIMITS as BoardLimits)
const CONFIG_TRIES = [
  '.claude/dispatch-config.json',
  'C:/Users/88691/Documents/Claude/Stock-web/.claude/dispatch-config.json',
  'C:/Users/88691/.claude/claude-dev-system/config/dispatch-config.json',
]

const USAGE_FILE = 'C:/Users/88691/.claude/state/usage.json'
const STORE_KEY = 'board-v1'
const LIMIT_RE = /總時限\s*(\d+)\s*分/
/** agent 回報格式「進度 已完成/總數」（2026-10-14 派工規矩） */
const PROG_RE = /進度\s*(?:約\s*)?(\d+)\s*[/／]\s*(\d+)/
const ETA_RE = /預計還(?:需|要)\s*(?:約)?\s*(\d+)\s*分/

function fmtMin(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60000))
  return m >= 60 ? `${Math.floor(m / 60)}時${m % 60}分` : `${m}分`
}

function fmtTok(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`
}

function fmtReset(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const t = new Date(d.getTime() + 8 * 3600_000)
  return `${t.getUTCMonth() + 1}/${t.getUTCDate()} ${String(t.getUTCHours()).padStart(2, '0')}:${String(t.getUTCMinutes()).padStart(2, '0')}`
}

/** 預計還需多久：agent 回報的預估（扣掉回報後經過的時間）優先，否則用「時限 − 已跑」當上限（標估）。 */
function etaText(t: BoardTask, now: number): string {
  if (t.endedAt) return '已結束'
  if (t.etaMin != null && t.etaAt) {
    const left = t.etaMin * 60000 - (now - t.etaAt)
    return left > 0 ? `約 ${fmtMin(left)}` : '應快完成'
  }
  if (t.limitMin) {
    const left = t.limitMin * 60000 - (now - t.startedAt)
    return left > 0 ? `≤${fmtMin(left)}（估）` : '已超過時限'
  }
  return '—'
}

/**
 * 預估剩餘（2026-10-13 使用者：「用已跑時間的一成來估…沒意義吧，要真的精確讓我知道剩多久才有意義」）：
 * ①agent 回報「進度 a/b」兩次以上且有前進 → 用兩次回報之間的實際速度算剩下的量要多久（最準）；
 * ②只有「預計還需 N 分」→ 用它扣掉回報後經過的時間；③都沒有 → 派工的「總時限 N 分」；主對話預設 5 分；
 * 超過預估不編數字：回傳 overMs，顯示「已超過預估 X，等最新回報」，收到新回報立刻重算。
 */
type Estimate = { leftMs?: number; overMs?: number; basis: string; pct?: number }
function estimateLeft(t: BoardTask, now: number): Estimate {
  const ran = now - t.startedAt
  const pct = t.progTotal ? Math.min(99, Math.round(((t.progDone ?? 0) / t.progTotal) * 100)) : undefined
  let left: number | undefined
  let basis = ''
  if (t.progTotal && t.progDone != null && t.progAt && t.prog0At != null && t.prog0Done != null && t.progDone > t.prog0Done && t.progAt > t.prog0At) {
    const rate = (t.progDone - t.prog0Done) / (t.progAt - t.prog0At)
    left = (t.progTotal - t.progDone) / rate - (now - t.progAt)
    basis = `依進度 ${t.progDone}/${t.progTotal} 的實際速度`
  } else if (t.etaMin != null && t.etaAt) {
    left = t.etaMin * 60000 - (now - t.etaAt)
    basis = 'agent 回報的預估'
  } else if (t.limitMin) {
    left = t.limitMin * 60000 - ran
    basis = '派工時限（尚無回報）'
  } else if (t.id.startsWith('main-')) {
    left = 5 * 60000 - ran
    basis = '主對話預設'
  }
  if (left == null) return { basis: '等第一次回報', pct }
  if (left > 0) return { leftMs: left, basis, pct }
  return { overMs: -left, basis, pct }
}
/** 超過預估 10 分還沒新回報＝該去追問 */
const STALE_OVER_MS = 10 * 60000
function leftText(t: BoardTask, now: number): string {
  const e = estimateLeft(t, now)
  if (e.leftMs != null) return `約 ${fmtMin(e.leftMs)}（${e.basis}）`
  if (e.overMs != null) return `已超過預估 ${fmtMin(e.overMs)}，等最新回報${e.overMs >= STALE_OVER_MS ? '（⚠ 逾時未回報，該追問）' : ''}`
  return e.basis
}

async function refreshLimits($: EngineInterface, now: number) {
  const files: Array<[string, string | undefined]> = []
  for (const path of CONFIG_TRIES) {
    try {
      files.push([path, await $.fs.read(path)])
    } catch {
      files.push([path, undefined])
    }
  }
  const today = new Date(now + 8 * 3600_000).toISOString().slice(0, 10)
  const next = chooseLimits(files, today)
  await update($, limitsAtom, p => (JSON.stringify(p) === JSON.stringify(next) ? p : next))
}

async function refreshUsage($: EngineInterface) {
  try {
    const now = Date.now()
    await refreshLimits($, now)
    // 優先讀用量守門 hook 寫的用量檔（每則訊息與工具後更新，重開 VSCode 也有）；讀不到才用這次執行的 API 回應
    let next: BoardUsage | undefined
    try {
      const f = JSON.parse(await $.fs.read(USAGE_FILE)) as { five_hour_pct?: number; five_hour_resets_at?: string; seven_day_pct?: number; seven_day_resets_at?: string }
      if (typeof f.five_hour_pct === 'number')
        next = { five: f.five_hour_pct, fiveResetsAt: f.five_hour_resets_at, seven: f.seven_day_pct, sevenResetsAt: f.seven_day_resets_at, at: now }
    } catch {
      next = undefined
    }
    if (!next) {
      const u = await $.session.usage()
      const five = u.rateLimits.find(r => r.kind === 'five_hour')
      const seven = u.rateLimits.find(r => r.kind === 'seven_day')
      next = { five: five?.percentUsed, fiveResetsAt: five?.resetsAt, seven: seven?.percentUsed, sevenResetsAt: seven?.resetsAt, at: now }
    }
    const prev = await read($, usage)
    if (next.five != null) {
      const pct = next.five
      await update($, usageHist, h => {
        const last = h[h.length - 1]
        const keep = h.filter(([t]) => now - t < 6 * 3600_000)
        return last && last[1] === pct && now - last[0] < 300_000 ? keep : [...keep, [now, pct] as [number, number]].slice(-1500)
      })
    }
    await update($, usage, p => (next.five == null && next.seven == null ? { ...p, at: now } : next))
    // 不在這裡用「重置時間變了」清任務（2026-10-12 真正的根因：用量端點的重置時間每次在 20:49:59 與 20:50:00 之間跳，
    // 取到分鐘比對就誤判換窗口、把已結束的主對話紀錄全清掉）。換窗口清理只由 pushStatus 依「結束時間早於窗口開始」做。
    void prev
  } catch {
    // 讀不到就保留上一次
  }
}

async function refreshGit($: EngineInterface) {
  try {
    const st = await $.process.run(['git', 'status', '--short'], { timeoutMs: 5000 })
    const lg = await $.process.run(['git', 'log', '--oneline', '-1'], { timeoutMs: 5000 })
    if (st.exitCode !== 0) return
    // 這個 5 小時窗口內的 commit＝已完成項目（使用者 10/11：要看到這 5 小時內完成了什麼）
    const us = await read($, usage)
    const reset = us.fiveResetsAt ? Date.parse(us.fiveResetsAt) : NaN
    const since = new Date((Number.isFinite(reset) ? reset : Date.now()) - 5 * 3600_000).toISOString()
    const cm = await $.process.run(['git', 'log', `--since=${since}`, '--pretty=format:%h %at %ad %s', '--date=format:%H:%M'], { timeoutMs: 5000 })
    const next: BoardGit = {
      dirty: st.stdout.split(/\r?\n/).filter(l => l.trim()).length,
      last: lg.stdout.trim().slice(0, 60),
      at: Date.now(),
      commits: cm.exitCode === 0 ? cm.stdout.split(/\r?\n/).filter(l => l.trim()).slice(0, 30) : [],
    }
    await update($, git, () => next)
  } catch {
    // 不是 git 專案或執行失敗就略過
  }
}


/**
 * 派出時間補回（2026-10-13 使用者：「任務…已跑時間及預估剩餘時間，要有確保都有數值」——看板重新載入後，載入前就在跑的 agent
 * 沒有派出紀錄，原本只顯示「無法計時」）：每個 subagent 派出時引擎會寫一次 `subagents/agent-<id>.meta.json`，
 * 用它的修改時間當派出時間（之後不再改寫）。每分鐘最多列一次目錄。
 */
const spawnTimes = new Map<string, number>()
let spawnListedAt = 0
async function loadSpawnTimes($: EngineInterface) {
  if (Date.now() - spawnListedAt < 60_000) return
  spawnListedAt = Date.now()
  try {
    const sid = await $.session.id()
    const dir = `C:/Users/88691/.claude/projects/c--Users-88691-Documents-Claude-Stock-web/${sid}/subagents`
    for (const f of await $.fs.list(dir)) {
      const m = f.name.match(/^agent-(.+)\.meta\.json$/)
      if (m && m[1] && f.mtimeMs > 0) spawnTimes.set(m[1], f.mtimeMs)
    }
  } catch {
    // 目錄不存在（沒派過 agent）或讀不到就略過
  }
}

/**
 * 精簡版看板寫進狀態列（輸入框下方）：VSCode 聊天面板不一定有位置畫 Pane，狀態列各介面都會顯示（遠端可到 10000 字）。
 * 每個事件與每 30 秒更新一次。
 */
async function pushStatus($: EngineInterface) {
  try {
    const now = Date.now()
    await loadSpawnTimes($)
    const all = { ...(await read($, tasks)) }
    {
      // 載入前就在跑的任務：用 meta.json 時間補回派出時間，改成正常計時
      const fixed: Record<string, BoardTask> = {}
      for (const t of Object.values(all)) {
        const at = spawnTimes.get(t.id)
        if (t.preBoard && at) fixed[t.id] = { ...t, startedAt: at, preBoard: false }
      }
      if (Object.keys(fixed).length) {
        Object.assign(all, fixed)
        await update($, tasks, a => ({ ...a, ...fixed }))
      }
    }
    {
      // 換到新的 5 小時窗口：結束時間早於這個窗口開始的任務清掉（重開後也成立）
      const u0 = await read($, usage)
      const r0 = u0.fiveResetsAt ? Date.parse(u0.fiveResetsAt) : NaN
      if (Number.isFinite(r0)) {
        const ws = r0 - 5 * 3600_000
        const stale = Object.values(all).filter(t => t.endedAt && t.endedAt < ws).map(t => t.id)
        if (stale.length) {
          for (const id of stale) delete all[id]
          await update($, tasks, a => Object.fromEntries(Object.entries(a).filter(([id]) => !stale.includes(id))))
        }
      }
    }
    const us = await read($, usage)
    let live: Awaited<ReturnType<typeof $.agent.list>> = []
    try {
      live = await $.agent.list()
    } catch {
      live = []
    }
    const liveStatus = new Map(live.map(a => [a.id, a.status as string]))
    // 已完成／失敗的任務留到這個 5 小時窗口結束（使用者 10/11）：結束狀態寫回 state，agent 從清單消失也保留；
    // 失敗的之後被接續完成（同一個 id 變 completed）就改歸已完成。
    const isEnd = (st: string) => st === 'completed' || st === 'failed' || st === 'killed'
    const changes: Record<string, BoardTask> = {}
    for (const t of Object.values(all)) {
      const st = liveStatus.get(t.id)
      const fin = st === undefined ? (t.finalStatus ?? (t.id.startsWith('main-') ? 'running' : 'completed')) : st
      if (isEnd(fin) && (t.finalStatus !== fin || !t.endedAt)) changes[t.id] = { ...t, finalStatus: fin, endedAt: t.endedAt ?? now, fiveEnd: t.fiveEnd ?? us.five }
      else if (!isEnd(fin) && t.finalStatus) changes[t.id] = { ...t, finalStatus: undefined, endedAt: undefined }
    }
    // 看板啟動前就派出的 agent 也收進紀錄（之後從系統清單消失仍保留到窗口結束）
    for (const a of live) {
      if (all[a.id] || changes[a.id]) continue
      const fin = a.status as string
      changes[a.id] = {
        id: a.id,
        description: a.description,
        model: a.type,
        startedAt: spawnTimes.get(a.id) ?? now,
        tokens: 0,
        cacheRead: 0,
        preBoard: !spawnTimes.has(a.id),
        ...(isEnd(fin) ? { finalStatus: fin, endedAt: now } : {}),
      }
    }
    if (Object.keys(changes).length) await update($, tasks, a => ({ ...a, ...changes }))
    for (const [id, t] of Object.entries(changes)) all[id] = t
    const statusOf = new Map<string, string>(Object.values(all).map(t => [t.id, t.finalStatus ?? liveStatus.get(t.id) ?? 'running']))
    for (const a of live) if (!statusOf.has(a.id)) statusOf.set(a.id, a.status)
    const mainTok = await read($, mainTokens)
    const totalTok = mainTok + Object.values(all).reduce((s2, t) => s2 + t.tokens, 0)
    // 占比＝任務開始到結束（執行中＝到現在）5 小時用量 % 的差（2026-10-11 使用者：舊的 token 比例法重開後會失真成 49.5%）；同時段平行任務會重疊
    // 用量端點只給整數 %（2026-10-12 使用者：有 token 卻顯示 0%）：差值 0 但有花 token 顯示「<1%」
    const pctTxt = (d: number, used: boolean) => (d < 1 && used ? '<1%' : `${d.toFixed(0)}%`)
    const shareOf = (t: BoardTask) => (t.fiveStart != null && us.five != null ? pctTxt(Math.max(0, (t.fiveEnd ?? us.five) - t.fiveStart), t.tokens > 0) : '—')
    void totalTok
    void shareOf
    const lim = await read($, limitsAtom)
    const warn = (us.five ?? 0) >= lim.fiveHour || (us.seven ?? 0) >= lim.sevenDay
    const head = `📋 額度 5h ${us.five ?? '—'}%（重置 ${fmtReset(us.fiveResetsAt)}）／7d ${us.seven ?? '—'}%${warn ? ' ⚠收尾門檻' : ''}`
    const running = Object.values(all).filter(t => {
      const st = statusOf.get(t.id)
      return st === 'running' || st === 'pending' || st === 'waiting'
    })
    const untracked = live.filter(a => !all[a.id] && (a.status === 'running' || a.status === 'pending' || a.status === 'waiting'))
    const lines = [
      head,
      ...running.map(t => `▶ ${t.description}｜已跑 ${fmtMin(now - t.startedAt)}｜${leftText(t, now)}`),
      ...untracked.map(a => `▶ ${a.description}（${a.status}，看板啟動前已在跑）`),
    ]
    if (running.length + untracked.length === 0) lines.push('目前沒有執行中的任務')
    const NL = String.fromCharCode(10)
    $.ui.status(lines.join(NL))
    // VSCode 聊天面板不顯示外掛面板與狀態列（2026-10-11 使用者截圖確認）：同步寫成 Markdown 檔，
    // 在 VSCode 用「開啟預覽」（Ctrl+K V）看，檔案更新時預覽會自動刷新。
    const g = await read($, git)
    // HTML 版看板（2026-10-11 使用者：左右留白再少、排版好讀）：VSCode Markdown 預覽會照樣畫檔內 HTML 與 <style>。
    const esc = (x: string) => x.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    const stZh = (st: string) =>
      ({ running: '執行中', pending: '排隊中', waiting: '等待中', idle: '閒置', completed: '已完成', failed: '失敗', killed: '已結束（交完報告後主動停止）' })[st] ?? st
    // 被停止＝照 CLAUDE.md 交完最終報告後由主對話 TaskStop，歸已完成（2026-10-12 使用者：紅色「已停止」看起來像失敗）
    const kind = (st: string) =>
      st === 'running' ? 'run' : st === 'pending' || st === 'waiting' || st === 'idle' ? 'wait' : st === 'failed' ? 'fail' : 'done'
    const icon = (st: string) => ({ run: '🟢', wait: '🟡', fail: '🔴', done: '✅' })[kind(st)]
    const meter = (label: string, pct: number | undefined, sub: string, limit: number) =>
      `<div class="m${(pct ?? 0) >= limit ? ' warn' : ''}"><span class="ml">${label}</span><span class="bar"><i style="width:${Math.max(0, Math.min(100, pct ?? 0))}%"></i></span><b>${pct ?? '—'}%</b></div><div class="sub">${sub}</div>`
    const row = (ic: string, text: string, cls = '') => `<div class="r ${cls}"><span class="ic">${ic}</span><span>${text}</span></div>`
    const sec = (title: string, n?: number) => `<div class="sec">${title}${n != null ? ` <span class="n">${n}</span>` : ''}</div>`
    // 已完成的主對話移到下方「主對話紀錄」一行一筆（2026-10-11 使用者：不要一直堆在任務上面）
    const isMainDone = (t: BoardTask) => t.id.startsWith('main-') && !!t.endedAt
    // 不再只留 30 筆（2026-10-12）：全部列出，超過 30 筆時只顯示最新 30 筆並註明另有幾筆
    // 2026-10-13 使用者：「看板任務留正在執行的任務就好了，已完成就不用了，5小時內完成的也可以刪了，我去github看記錄就好」——
    // 只列執行中／等待中（已完成、已停止、失敗都不列）；資料照存，只是不顯示。
    const isActive = (t: BoardTask) => {
      if (t.endedAt) return false
      const k = kind(statusOf.get(t.id) ?? 'completed')
      return k === 'run' || k === 'wait'
    }
    const taskList = Object.values(all)
      .filter(t => !isMainDone(t) && isActive(t))
      .sort((a, b) => Number(!!a.endedAt) - Number(!!b.endedAt) || b.startedAt - a.startedAt)
      .slice(0, 20)
    const card = (t: BoardTask): string => {
      const st = statusOf.get(t.id) ?? 'completed'
      const k = kind(st)
      const ran = (t.endedAt ?? now) - t.startedAt
      const lines: string[] = [`<div class="ct">${icon(st)} ${esc(t.description)}</div>`]
      if (t.preBoard) {
        lines.push(`<div class="cm">${stZh(st)}｜派出紀錄在看板重新載入時遺失，無法計時</div>`)
      } else {
        if (k === 'run' || k === 'wait') {
          const est = estimateLeft(t, now)
          lines.push(`<div class="cm">${stZh(st)}｜已跑 ${fmtMin(ran)}｜${est.leftMs != null ? '預估剩 ' : ''}${esc(leftText(t, now))}</div>`)
          // 進度條：有回報進度就用實際完成比例，否則用時間比例；超過預估停在 99%
          const pct = est.pct ?? (est.leftMs != null ? Math.min(99, Math.round((ran / (ran + est.leftMs)) * 100)) : est.overMs != null ? 99 : 0)
          lines.push(`<div class="m${est.overMs != null && est.overMs >= STALE_OVER_MS ? ' warn' : ''}"><span class="bar"><i style="width:${pct}%"></i></span><b>${pct}%</b></div>`)
        } else lines.push(`<div class="cm">${stZh(st)}｜共 ${fmtMin(ran)}</div>`)
        if (t.lastMsg) lines.push(`<div class="cm">💬 ${fmtMin(now - (t.lastMsgAt ?? now))}前：${esc(t.lastMsg.slice(0, 60))}</div>`)
      }
      return `<div class="card ${k}">${lines.join('')}</div>`
    }
    const todos = await readTodos($)
    const decisions = await readDecisions($)
    const checks = await readChecks($)
    const doneToday = await readDoneToday($)
    const userTests = await readUserTests($)
    // 每筆 commit 的期間用量：這筆與上一筆（或窗口開始）之間 5 小時用量增加多少（含同時間平行任務）；看板啟動前沒有取樣＝—
    const hist = await read($, usageHist)
    const pctAt = (t: number): number | undefined => {
      let v: number | undefined
      for (const [ht, hp] of hist) {
        if (ht <= t) v = hp
        else break
      }
      return v
    }
    const resetMs = us.fiveResetsAt ? Date.parse(us.fiveResetsAt) : NaN
    const windowStart = Number.isFinite(resetMs) ? resetMs - 5 * 3600_000 : undefined
    const parsed = (g.commits ?? []).map(c => {
      const [hash, at, time, ...rest] = c.split(' ')
      return { hash: hash ?? '', at: Number(at) * 1000, time: time ?? '', msg: rest.join(' ') }
    })
    const commits = parsed.map((c, i) => {
      const prevAt = parsed[i + 1]?.at ?? windowStart
      const a = pctAt(c.at)
      const b = prevAt != null ? (prevAt === windowStart && hist.length && hist[0]![0] <= prevAt + 60_000 ? 0 : pctAt(prevAt)) : undefined
      const d = a != null && b != null ? Math.max(0, a - b) : undefined
      const useTxt = d != null ? `<span class="u">${d < 1 ? '<1%' : `${d.toFixed(0)}%`}</span>` : '<span class="u">—</span>'
      return row('✅', `<span class="t">${c.time}</span> ${esc(c.msg.slice(0, 44))} ${useTxt}`)
    })
    const CSS = `<style>
html{padding:0!important;margin:0!important}
body,body.scrollBeyondLastLine{padding:8px!important;margin:0!important;max-width:none!important;font-size:13px!important;line-height:1.45!important}
.hd{display:flex;justify-content:space-between;align-items:baseline;margin:2px 0 6px}
.hd b{font-size:15px}.hd span{font-size:11px;opacity:.6}
.m{display:flex;align-items:center;gap:6px;margin:3px 0 0}.ml{width:2.2em;flex:none;opacity:.8}
.bar{flex:1;height:8px;border-radius:4px;background:rgba(127,127,127,.25);overflow:hidden;display:block}
.bar i{display:block;height:100%;border-radius:4px;background:#4c9ffe}
.m b{width:3.2em;text-align:right;flex:none}
.m.warn .bar i{background:#e5534b}.m.warn b{color:#e5534b}
.sub{font-size:11px;opacity:.6;margin:0 0 4px 2.8em}
.sec{margin:10px 0 4px;padding-bottom:2px;border-bottom:1px solid rgba(127,127,127,.3);font-size:12px;font-weight:600;opacity:.85}
.sec .n{font-weight:400;opacity:.7}
.r{display:flex;gap:5px;margin:2px 0;align-items:flex-start}.ic{flex:none;width:1.3em}
.r .t{opacity:.6;font-size:11px}.r .h{opacity:.45;font-size:10px}.r .u{font-size:11px;color:#d29922;white-space:nowrap}.sb{margin:0 0 3px 1.8em;font-size:12px;opacity:.75}.sb div{margin:1px 0}
.card{margin:5px 0;padding:4px 7px;border-left:3px solid #4c9ffe;border-radius:4px;background:rgba(127,127,127,.08)}
.card.done{border-color:#3fb950}.card.fail{border-color:#e5534b}.card.wait{border-color:#d29922}
.ct{font-weight:600}.cm{font-size:12px;opacity:.8}
.foot{margin-top:10px;font-size:10px;opacity:.5}
</style>`
    void commits // 已不顯示（10/13），保留計算以免更動 git 讀取流程
    const html = [
      CSS,
      `<div class="hd"><b>📋 任務看板</b><span>更新 ${fmtReset(new Date(now).toISOString())}</span></div>`,
      meter('5h', us.five, `重置 ${fmtReset(us.fiveResetsAt)}`, lim.markFive),
      meter('7d', us.seven, `重置 ${fmtReset(us.sevenResetsAt)}`, lim.markSeven),
      warn ? row('⚠', '<b>已達收尾門檻</b>') : '',
      row('🗂', `未提交 ${g.dirty}｜最新 ${esc((g.last || '—').slice(0, 7))}`),
      sec('任務', taskList.length),
      taskList.length ? taskList.map(card).join('') : row('😴', '目前沒有任務'),
      // 2026-10-13 使用者：「主對話記錄我覺得不用保留了，留下在執行中項目的就好」——已完成的主對話不再列出（資料仍存，只是不顯示）。
      userTests.items.length
        ? sec('🧪 等你測試／處理', userTests.items.length) + (userTests.note ? `<div class="sb">${esc(userTests.note)}</div>` : '') +
          userTests.items.map(t => row('🧪', `<b>${esc(t.name)}</b>`) + (t.detail ? `<div class="sb"><div>${esc(t.detail)}</div></div>` : '')).join('')
        : '',
      todos.length
        ? sec('🟡 排隊中的待辦', todos.length) +
          todos
            .map(t => {
              const [head, ...subs] = t.split(String.fromCharCode(1))
              return row('🟡', `<b>${esc(head ?? '')}</b>`) + (subs.length ? `<div class="sb">${subs.map(x => `<div>· ${esc(x)}</div>`).join('')}</div>` : '')
            })
            .join('')
        : '',
      decisions.length ? sec('🤔 待商量／決定', decisions.length) + decisions.map(d => row('🤔', esc(d))).join('') : '',
      // 2026-10-13 使用者：「待商量／決定移動到待檢查上面」「待檢查要再分為定期檢查與一般的檢查事項」——以「每」開頭（每天／每週／每季／每年…）的歸定期。
      (() => {
        const periodic = checks.filter(c => c.text.startsWith('每'))
        const once = checks.filter(c => !c.text.startsWith('每'))
        // 2026-10-13 使用者：「等你測試／待檢查寫得太模糊，看不懂」→ 名稱粗體＋下一行寫要看哪裡、看什麼。
        const line = (c: { text: string; detail: string; due: boolean }) =>
          row(c.due ? '⏰' : '🕒', `${c.due ? '到期 ' : ''}<b>${esc(c.text)}</b>`) + (c.detail ? `<div class="sb"><div>${esc(c.detail)}</div></div>` : '')
        return (once.length ? sec('🕒 待檢查（一般）', once.length) + once.map(line).join('') : '') +
          (periodic.length ? sec('🔁 定期檢查', periodic.length) + periodic.map(line).join('') : '')
      })(),
      // 「這 5 小時內完成」區塊 10/13 依使用者要求移除（完成紀錄看 GitHub）。
      doneToday.length ? sec('✅ 今日已完成（05:00 起）', doneToday.length) + doneToday.map(d => row('✅', esc(d))).join('') : '',
    ]
    const md = [html.filter(Boolean).join(NL)]
    await $.fs.write('C:/Users/88691/.claude/state/task-board.md', md.join(NL) + NL)
    await saveBoard($)
  } catch {
    // 狀態列失敗不影響其他功能
  }
}

/** 讀專案的 PROGRESS.md：先試工作目錄相對路徑，再試 Stock-web 絕對路徑；失敗原因寫進 state 方便除錯。 */
async function readProgress($: EngineInterface): Promise<string> {
  const tries = ['PROGRESS.md', 'C:/Users/88691/Documents/Claude/Stock-web/PROGRESS.md']
  const errs: string[] = []
  for (const path of tries) {
    try {
      const t = await $.fs.read(path)
      if (typeof t === 'string' && t.length > 0) return t
    } catch (err) {
      errs.push(`${path}: ${err instanceof Error ? err.message : String(err)}`)
    }
  }
  try {
    await $.fs.write('C:/Users/88691/.claude/state/task-board-debug.txt', errs.join(String.fromCharCode(10)))
  } catch {
    // ignore
  }
  return ''
}

/**
 * 專案待辦（2026-10-11 使用者：「代辦事項不是還很多嗎?怎麼都沒寫在🟡」）：讀工作目錄的 PROGRESS.md
 * 「接手狀態」裡「下次從這裡開始（照順序）」的編號清單，沒標 ✅ 的照順序列出；沒有這個檔就略過。
 */
async function readTodos($: EngineInterface): Promise<string[]> {
  try {
    const src = await readProgress($)
    const start = src.indexOf('下次從這裡開始')
    if (start < 0) return []
    const rest = src.slice(start)
    const end = rest.search(/\r?\n\*\*(待使用者決定|排定的觀察|暫不做)/)
    const block = end > 0 ? rest.slice(0, end) : rest.slice(0, 6000)
    // 格式（CLAUDE.md 規則二第 7 點）：「N. 批次標題（說明）」＋縮排「- 細項名稱：細節」；看板顯示標題與細項名稱。
    const SEP = String.fromCharCode(1)
    const out: string[] = []
    for (const line of block.split(/\r?\n/)) {
      const m = line.match(/^(\d+[a-z]?)\.\s+(.*)$/)
      if (m && m[2] !== undefined) {
        if (m[2].includes('✅')) continue
        const plain = m[2].replace(/\*\*|`/g, '').trim()
        out.push((plain.split(/[：（(]/)[0] ?? plain).trim().slice(0, 30))
        continue
      }
      const sub = line.match(/^\s+[-*]\s+(.*)$/)
      if (sub && sub[1] !== undefined && out.length) {
        const plain = sub[1].replace(/\*\*|`/g, '').trim()
        if (plain.includes('✅')) continue
        const name = (plain.split(/[：（(]/)[0] ?? plain).trim().slice(0, 24)
        out[out.length - 1] += SEP + name
      }
    }
    return out.slice(0, 25).map((t, i) => `${i + 1}. ${t}`)
  } catch {
    return []
  }
}

/**
 * 待商量／決定（2026-10-11 使用者：「還要有一個待商量及決定的項目，顯示像之前提到的日韓股、登入、LINE、完整8大面向這類的」）：
 * 讀 PROGRESS.md 的「**待使用者決定**」與「**暫不做…**」兩行，依「、」拆成項目；暫不做的標「暫緩」。
 */
type BoardSnap = { tasks?: Record<string, BoardTask>; usageHist?: Array<[number, number]>; mainTokens?: number; currentMain?: string }

/** 存一份到跨對話的永久儲存（2026-10-11 使用者：重開 VSCode 後已完成主對話不見了）。 */
async function saveBoard($: EngineInterface) {
  try {
    // 存檔前一定先完成還原（2026-10-12 使用者：輸入新訊息後主對話紀錄又不見）：新程序啟動時 prompt.submit 可能比 session.start 的還原先觸發，
    // 先存檔就會用「只有新任務」蓋掉永久儲存，還原時讀到的已是空的。
    await ensureRestored($)
    const snap: BoardSnap = {
      tasks: await read($, tasks),
      usageHist: await read($, usageHist),
      mainTokens: await read($, mainTokens),
      currentMain: await read($, currentMain),
    }
    await $.store.set(STORE_KEY, snap)
  } catch {
    // ignore
  }
}

let restoring: Promise<void> | undefined
/** 每次載入（模組變數重置）只還原一次；所有存檔都等它完成。 */
function ensureRestored($: EngineInterface): Promise<void> {
  restoring ??= restoreBoard($)
  return restoring
}

/** 載入時從永久儲存還原（只在這次執行還是空的時候）。 */
async function restoreBoard($: EngineInterface) {
  try {
    // 合併而非「記憶體空才還原」（2026-10-12 使用者：主對話紀錄 5 小時還沒到就不見）：重新載入時若先進來一筆新任務，
    // 舊寫法會整批跳過還原，下次存檔就只剩新的；同一筆以記憶體中（較新）的為準。
    const snap = (await $.store.get(STORE_KEY)) as BoardSnap | undefined
    if (!snap) return
    if (snap.tasks) await update($, tasks, cur => ({ ...(snap.tasks ?? {}), ...cur }))
    if (snap.usageHist) await update($, usageHist, cur => [...(snap.usageHist ?? []), ...cur].sort((a, b) => a[0] - b[0]).slice(-1500))
    if (typeof snap.mainTokens === 'number') await update($, mainTokens, cur => cur + (snap.mainTokens ?? 0))
    if (snap.currentMain) await update($, currentMain, cur => cur || snap.currentMain || '')
  } catch {
    // ignore
  }
}

/**
 * 待檢查（2026-10-11 使用者：「看板可以再新增一項是看待檢查的項目，像是甚麼開盤要檢查的項目…到了檢查時間並且正在執行檢查了，就移動到執行中的任務」）：
 * 讀 PROGRESS「**排定的觀察／檢查**」那行，依「；」拆項；含 M/D 日期且已到（台北今天以前）的標 ⏰ 排最上。
 * 實際開始檢查時，那一輪主對話或驗證 agent 會出現在「任務」區；做完由我從 PROGRESS 移除，這裡就消失。
 */
async function readChecks($: EngineInterface): Promise<Array<{ text: string; detail: string; due: boolean; date?: string }>> {
  try {
    const src = await readProgress($)
    const line = src.split(/\r?\n/).find(l => l.startsWith('**排定的觀察'))
    if (!line) return []
    const body = line.replace(/^\*\*[^*]+\*\*[：:]\s*/, '')
    const tw = new Date(Date.now() + 8 * 3600_000)
    const today = (tw.getUTCMonth() + 1) * 100 + tw.getUTCDate()
    const out: Array<{ text: string; detail: string; due: boolean; date?: string }> = []
    for (const part of body.replace(/（[^）]*）/g, x => x.replace(/[；;]/g, '，')).split(/[；;]/)) {
      const text = part.replace(/\*\*|`/g, '').replace(/。$/, '').trim()
      if (!text) continue
      const [nm, ...restParts] = text.split('：')
      const name = (nm ?? text).trim()
      const dates = [...name.matchAll(/(\d{1,2})\/(\d{1,2})/g)].map(m => Number(m[1]) * 100 + Number(m[2]))
      const first = dates.length ? Math.min(...dates) : undefined
      // 2026-10-13 使用者：看板要像排隊清單一樣一看就懂 → 只顯示「：」前的短名（日期｜名稱），細節留在 PROGRESS。
      out.push({ text: name.slice(0, 40), detail: restParts.join('：').trim().slice(0, 140), due: first != null && first <= today, date: first != null ? `${Math.floor(first / 100)}/${first % 100}` : undefined })
    }
    return out.sort((a, b) => Number(b.due) - Number(a.due)).slice(0, 25)
  } catch {
    return []
  }
}

/**
 * 今日已完成（2026-10-13 使用者：「看板最下面再新增一個今日已完成項目，每天凌晨5點開始新紀錄…到下個凌晨5點再清空」）：
 * 讀 PROGRESS「**今日已完成（YYYY-MM-DD 05:00 起）**：項目；項目」那一行；日期要等於「台北時間減 5 小時」的日期才顯示，
 * 過了隔天 05:00 自動不顯示（等同清空），內容由主對話整理成精簡句子寫入，不是自動抓 commit。
 */
async function readDoneToday($: EngineInterface): Promise<string[]> {
  try {
    const src = await readProgress($)
    const line = src.split(/\r?\n/).find(l => l.startsWith('**今日已完成（'))
    if (!line) return []
    const m = line.match(/^\*\*今日已完成（(\d{4}-\d{2}-\d{2})[^*]*\*\*[：:]\s*(.*)$/)
    if (!m || !m[1] || m[2] === undefined) return []
    const boardDay = new Date(Date.now() + 8 * 3600_000 - 5 * 3600_000).toISOString().slice(0, 10)
    if (m[1] !== boardDay) return []
    // 只顯示「：」前的短名（PROGRESS 寫成「短名：細節」），細節給接手用。
    return m[2].replace(/。$/, '').split(/[；;]/).map(x => x.replace(/\*\*|`/g, '').trim()).filter(Boolean).map(x => (x.split('：')[0] ?? x).trim().slice(0, 40)).slice(0, 40)
  } catch {
    return []
  }
}

/** 等使用者測試／處理（PROGRESS「**待使用者**：短名：細節；短名：細節」）：看板放在「排隊中的待辦」上面。 */
async function readUserTests($: EngineInterface): Promise<{ items: Array<{ name: string; detail: string }>; note: string }> {
  try {
    const src = await readProgress($)
    const line = src.split(String.fromCharCode(10)).map(l => l.replace(String.fromCharCode(13), '')).find(l => l.startsWith('**待使用者**'))
    if (!line) return { items: [], note: '' }
    let body = line.replace(/^\*\*[^*]+\*\*[：:]\s*/, '').replace(/。$/, '')
    // 結尾括號是整區附註（例：「以上都等部署上線後再試」），取「；」前第一段當附註，其餘（已確認項）不顯示
    let note = ''
    const tail = body.match(/（([^）]*)）$/)
    if (tail && tail[1] !== undefined) {
      note = (tail[1].split(/[；;]/)[0] ?? '').trim()
      body = body.slice(0, tail.index)
    }
    const items = body
      .split(/[；;]/)
      .map(x => x.replace(/\*\*|`/g, '').trim())
      .filter(x => x && !x.startsWith('目前沒有'))
      .map(x => {
        const [nm, ...rest] = x.split('：')
        return { name: (nm ?? x).trim().slice(0, 40), detail: rest.join('：').trim().slice(0, 140) }
      })
      .slice(0, 15)
    return { items, note }
  } catch {
    return { items: [], note: '' }
  }
}

async function readDecisions($: EngineInterface): Promise<string[]> {
  try {
    const src = await readProgress($)
    const out: string[] = []
    for (const line of src.split(/\r?\n/)) {
      // 2026-10-13 使用者：「待商量／決定裡有些是等我測試…要分開，等我測試這類擺在排隊中的待辦上面」——「待使用者」改由 readUserTests 讀。
      const m = line.match(/^\*\*(待使用者決定|暫不做)[^*]*\*\*[：:]\s*(.*)$/)
      if (!m || m[2] === undefined) continue
      const tag = m[1] === '暫不做' ? '（暫緩）' : '（待決定）'
      // 2026-10-13 使用者看不懂被拆碎的項目（「建議卡「」」「目前沒有（待決定）」）：改以「；」分項、保留括號內容、
      // 「目前沒有…」不列；每項取「：」前的短名（PROGRESS 這三行一律寫成「短名：細節；短名：細節」）。
      const body = m[2].replace(/。$/, '')
      // 括號內的「；」不當分項（10/13「其餘照建議代決…」被拆成一項）：先把全形括號內的分號換成逗號。
      for (const part of body.replace(/（[^）]*）/g, x => x.replace(/[；;]/g, '，')).split(/[；;]/)) {
        const item = part.replace(/\*\*|`/g, '').trim()
        if (!item || item.startsWith('目前沒有')) continue
        out.push(`${(item.split('：')[0] ?? item).trim().slice(0, 40)}${tag}`)
      }
    }
    return out.slice(0, 12)
  } catch {
    return []
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'board', description: '打開任務看板（agent 進度、預計完成、token、額度）' })
    void $.ui.open({ id: PANE, title: '任務看板' })
    await ensureRestored($)
    void refreshUsage($)
    void refreshGit($)
    // 看板每 15 秒更新（2026-10-13 使用者：「看板改成15秒更新」，原 10/11 每 5 秒）；git 每 30 秒（第 2 次）才跑一次，避免頻繁啟動 git 程序。
    let tick = 0
    $.clock.every(15_000, () => {
      tick += 1
      if (tick % 2 === 0) void refreshGit($)
      void refreshUsage($).then(() => pushStatus($))
    })
    void refreshUsage($).then(() => pushStatus($))
    return next(e)
  })

  on('command.run', { command: 'board' }, async $ => {
    await pushStatus($)
    const r = await $.ui.open({ id: PANE, title: '任務看板' })
    return { text: r.isPlaced ? '任務看板已開啟。' : '任務看板已建立，但這個介面目前沒有位置可以顯示面板。' }
  })

  on('agent.spawn', async ($, e, next) => {
    const r = await next(e)
    if (r.agentId) {
      const now = Date.now()
      const limit = e.prompt.match(LIMIT_RE)
      const task: BoardTask = {
        id: r.agentId,
        description: e.description,
        model: r.model,
        startedAt: now,
        limitMin: limit ? Number(limit[1]) : undefined,
        tokens: 0,
        cacheRead: 0,
        fiveStart: (await read($, usage)).five,
      }
      await update($, tasks, all => ({ ...all, [task.id]: task }))
      void pushStatus($)
    }
    return r
  })

  // agent 用 SendMessage 回報進度：記下最後一則與「預計還需 N 分鐘」
  on('session.send', async ($, e, next) => {
    if (e.agentId) {
      const now = Date.now()
      const eta = e.text.match(ETA_RE)
      const prog = e.text.match(PROG_RE)
      const id = e.agentId
      await update($, tasks, all => {
        const t = all[id]
        if (!t) return all
        return {
          ...all,
          [id]: {
            ...t,
            lastMsg: e.text.replace(/\s+/g, ' ').slice(0, 80),
            lastMsgAt: now,
            ...(eta ? { etaMin: Number(eta[1]), etaAt: now } : {}),
            ...(prog
              ? {
                  progDone: Number(prog[1]),
                  progTotal: Number(prog[2]),
                  progAt: now,
                  // 第一次（或總數改變）當速度起點
                  ...(t.prog0At == null || t.progTotal !== Number(prog[2]) ? { prog0Done: Number(prog[1]), prog0At: now } : {}),
                }
              : {}),
          },
        }
      })
      void pushStatus($)
    }
    return next(e)
  })

  // 每個 turn 結束時累計 token（agentId 沒有＝主對話）
  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    const u = r.usage
    if (u) {
      const tok = (u.input_tokens ?? 0) + (u.output_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0)
      const cr = u.cache_read_input_tokens ?? 0
      const id = (e as { agentId?: string }).agentId
      if (id) {
        await update($, tasks, all => {
          const t = all[id]
          return t ? { ...all, [id]: { ...t, tokens: t.tokens + tok, cacheRead: t.cacheRead + cr } } : all
        })
      } else {
        await update($, mainTokens, n => n + tok)
        const cur = await read($, currentMain)
        if (cur) {
          await update($, tasks, all => {
            const t = all[cur]
            return t ? { ...all, [cur]: { ...t, tokens: t.tokens + tok, cacheRead: t.cacheRead + cr } } : all
          })
        }
      }
      void refreshUsage($).then(() => pushStatus($))
    }
    // 主對話這一輪結束＝這則訊息處理完：任務轉已完成
    if (!(e as { agentId?: string }).agentId) {
      const cur = await read($, currentMain)
      if (cur) {
        const now = Date.now()
        await refreshUsage($)
        const fiveNow = (await read($, usage)).five
        await update($, tasks, all => {
          const t = all[cur]
          return t ? { ...all, [cur]: { ...t, finalStatus: 'completed', endedAt: now, fiveEnd: fiveNow } } : all
        })
        await update($, currentMain, () => '')
        void pushStatus($)
      }
    }
    return r
  })

  // 使用者每送出一則訊息＝主對話一個任務（顯示訊息開頭 30 字）
  on('prompt.submit', async ($, e, next) => {
    await ensureRestored($)
    const now = Date.now()
    const id = `main-${now}`
    // 背景工作完成通知也會觸發 prompt.submit：改用通知摘要當標題，不顯示一串編號（2026-10-12）
    const notice = /<task-notification>/.test(e.text) ? (e.text.match(/<summary>([^<]*)<\/summary>/)?.[1] ?? '背景工作完成') : ''
    const text = notice ? `背景通知：${notice}` : e.text.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim()
    // 回覆途中收到的背景通知併進正在進行的那一筆，不另開一筆（否則把進行中的切成兩段，token 與占比都失真）
    if (notice && (await read($, currentMain))) return next(e)
    const task: BoardTask = {
      id,
      description: `主對話：${text.slice(0, 30) || '（無文字）'}`,
      model: 'main',
      startedAt: now,
      tokens: 0,
      cacheRead: 0,
      fiveStart: (await read($, usage)).five,
    }
    const prev = await read($, currentMain)
    await update($, tasks, all => {
      const out = { ...all, [id]: task }
      const p = prev ? out[prev] : undefined
      if (prev && p && !p.endedAt) out[prev] = { ...p, finalStatus: 'completed', endedAt: now, fiveEnd: task.fiveStart }
      return out
    })
    await update($, currentMain, () => id)
    void pushStatus($)
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const now = Date.now()
    const all = await read($, tasks)
    const us = await read($, usage)
    const g = await read($, git)
    const mainTok = await read($, mainTokens)
    let live: Awaited<ReturnType<typeof $.agent.list>> = []
    try {
      live = await $.agent.list()
    } catch {
      live = []
    }
    const statusOf = new Map(live.map(a => [a.id, a.status]))
    // 已不在清單或狀態為結束的，標記結束時間（只顯示用，不寫回）
    const rows = Object.values(all)
      .map(t => {
        const st = statusOf.get(t.id) ?? 'completed'
        const done = st === 'completed' || st === 'failed' || st === 'killed'
        return { t: done && !t.endedAt ? { ...t, endedAt: t.lastMsgAt ?? now } : t, st }
      })
      .sort((a, b) => Number(!!a.t.endedAt) - Number(!!b.t.endedAt) || b.t.startedAt - a.t.startedAt)
      .slice(0, 12)
    const untracked = live.filter(a => !all[a.id] && (a.status === 'running' || a.status === 'pending' || a.status === 'waiting'))
    const totalTok = mainTok + Object.values(all).reduce((s, t) => s + t.tokens, 0)
    const share = (tok: number) =>
      us.five != null && totalTok > 0 ? `${((tok / totalTok) * us.five).toFixed(1)}%（估）` : '—'
    void share
    const lim = await read($, limitsAtom)
    const warn = (us.five ?? 0) >= lim.fiveHour || (us.seven ?? 0) >= lim.sevenDay
    return (
      <Box flexDirection="column">
        <Text bold color={warn ? 'red' : undefined}>
          額度 5小時 {us.five ?? '—'}%（重置 {fmtReset(us.fiveResetsAt)}）｜7天 {us.seven ?? '—'}%（重置 {fmtReset(us.sevenResetsAt)}）
          {warn ? ' ⚠ 已達收尾門檻' : ''}
        </Text>
        <Text dimColor>
          git：未提交 {g.dirty} 個｜最新 {g.last || '—'}
        </Text>
        {rows.length === 0 && untracked.length === 0 && <Text dimColor>目前沒有任務。</Text>}
        {untracked.map(a => (
          <Text>
            ▶ {a.description}（{a.type}，{a.status}）｜看板啟動前就在跑，無法計時
          </Text>
        ))}
        {rows.map(({ t, st }) => (
          <Box flexDirection="column">
            <Text bold={!t.endedAt} dimColor={!!t.endedAt}>
              {t.endedAt ? '✓' : '▶'} {t.description}（{t.model}，{st}）
            </Text>
            <Text dimColor>
              {'  '}已跑 {fmtMin((t.endedAt ?? now) - t.startedAt)}｜{t.endedAt ? '已結束' : leftText(t, now)}
            </Text>
            {t.lastMsg && (
              <Text dimColor>
                {'  '}最後回報（{fmtMin(now - (t.lastMsgAt ?? now))}前）：{t.lastMsg}
              </Text>
            )}
          </Box>
        ))}
      </Box>
    )
  })
}
