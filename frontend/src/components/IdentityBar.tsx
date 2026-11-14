import { useEffect, useState } from 'react'

import { getIdentity, setIdentity, type Identity } from '@/api/client'

const ROLE_OPTIONS = ['模型负责人', '数据目录成员', '普通查看者']
const PRESET_OPERATORS = ['赵启明', '林知远', '钱多多', '访客']

/**
 * 值班身份切换：模型部署与目录维护的权限都按这份声明走。
 * 切换后会广播一次事件，让当前页面重新拉取可执行动作与只读状态。
 */
export default function IdentityBar() {
  const [current, setCurrent] = useState<Identity>(getIdentity())
  const [customOperator, setCustomOperator] = useState('')

  useEffect(() => {
    function onChange(event: Event) {
      setCurrent((event as CustomEvent<Identity>).detail)
    }
    window.addEventListener('identity-changed', onChange)
    return () => window.removeEventListener('identity-changed', onChange)
  }, [])

  function apply(next: Identity) {
    setIdentity(next)
    setCurrent(next)
    window.dispatchEvent(new CustomEvent<Identity>('identity-changed', { detail: next }))
  }

  return (
    <div className="identity-bar">
      <span className="identity-label">当前值班：{current.operator}</span>
      <select
        className="identity-select"
        value={current.role}
        onChange={(event) => apply({ ...current, role: event.target.value })}
        aria-label="切换角色"
      >
        {ROLE_OPTIONS.map((role) => <option key={role} value={role}>{role}</option>)}
      </select>
      <select
        className="identity-select"
        value={PRESET_OPERATORS.includes(current.operator) ? current.operator : ''}
        onChange={(event) => {
          if (event.target.value) apply({ ...current, operator: event.target.value })
        }}
        aria-label="切换操作人"
      >
        {!PRESET_OPERATORS.includes(current.operator) && <option value="">{current.operator}（自定义）</option>}
        {PRESET_OPERATORS.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
      <input
        className="identity-input"
        value={customOperator}
        placeholder="自定义操作人"
        onChange={(event) => setCustomOperator(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && customOperator.trim()) {
            apply({ ...current, operator: customOperator.trim() })
            setCustomOperator('')
          }
        }}
      />
      <button
        className="btn ghost"
        type="button"
        onClick={() => {
          if (customOperator.trim()) {
            apply({ ...current, operator: customOperator.trim() })
            setCustomOperator('')
          }
        }}
      >
        切换
      </button>
    </div>
  )
}
