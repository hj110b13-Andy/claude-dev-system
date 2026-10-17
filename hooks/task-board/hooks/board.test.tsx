import { describe, expect, test } from 'claude-code/testing'

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
