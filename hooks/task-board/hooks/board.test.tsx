import { describe, expect, test } from 'claude-code/testing'
import { chooseLimits, DEFAULT_LIMITS, parseLimits } from './limits'

describe('task-board', () => {
  for (const surface of ['terminal', 'vscode'] as const) {
    test(`Pane 在 ${surface} 畫出額度列與空任務提示`, async $ => {
      const m = await $.ui.mount({ plugin: 'task-board', surface, component: 'Pane', requestId: 'task-board', props: { title: '任務看板', isFocused: false, bodyColumns: 80 } as never })
      const tree = JSON.stringify(await m.drawn())
      expect(tree).toContain('額度 5小時')
      expect(tree).toContain('目前沒有任務')
    })
  }
})

describe('用量門檻讀 dispatch-config.json', () => {
  const cfg = JSON.stringify({
    plan: { current: 'max5x', max5x: { until: '2026-11-13' }, after: 'pro' },
    usageThresholdPct: { max5x: { fiveHour: 95, sevenDay: 99 }, pro: { fiveHour: 80, sevenDay: 97 } },
    boardMeterMarks: { fiveHour: 80, sevenDay: 97 },
  })
  test('方案期間內用 max5x 門檻 95／99，標線 80／97', () => {
    const r = parseLimits(cfg, '2026-10-17')
    expect(r).toMatchObject({ fiveHour: 95, sevenDay: 99, markFive: 80, markSeven: 97 })
  })
  test('到期日（含）起自動改用 plan.after 的 80／97', () => {
    expect(parseLimits(cfg, '2026-11-13')).toMatchObject({ fiveHour: 80, sevenDay: 97 })
  })
  test('依序嘗試：第一份壞掉換下一份，全部找不到用預設 80／97', () => {
    expect(chooseLimits([['a', undefined], ['b', 'not json'], ['c', cfg]], '2026-10-17')).toMatchObject({ fiveHour: 95, source: 'c' })
    expect(chooseLimits([['a', undefined]], '2026-10-17')).toEqual(DEFAULT_LIMITS)
    expect(DEFAULT_LIMITS).toMatchObject({ fiveHour: 80, sevenDay: 97 })
  })
})
