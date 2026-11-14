import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'

import { readActionMessage, request } from '@/api/client'

const ENDPOINT = '/api/catalog'
const columns = [
  "条目编号",
  "数据集名称",
  "业务域",
  "数据集编号",
  "更新频率",
  "数据等级",
  "负责人",
  "条目状态"
]
const actions = [
  "发布条目",
  "下线条目",
  "归档条目"
]
const statuses = [
  "草稿",
  "已发布",
  "已下线",
  "已归档"
]

type FieldDef = { 字段名: string; 类型: string; 说明: string }

type Row = Record<string, string | number | boolean | null | undefined> & {
  字段清单?: FieldDef[]
  字段清单来源?: string
  字段数?: number
  readonly?: boolean
}

export default function CatalogView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [message, setMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<number | null>(null)
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('目录条目列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据目录检索列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
    function onIdentity() {
      void reload()
    }
    window.addEventListener('identity-changed', onIdentity)
    return () => window.removeEventListener('identity-changed', onIdentity)
  }, [reload])

  async function runAction(action: string, row: Row) {
    setMessage('')
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const text = await readActionMessage(response, '数据目录检索动作未生效，请稍后重试')
      if (!response.ok) {
        throw new Error(text)
      }
      setMessage(text)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据目录检索操作失败')
    }
  }

  const stats = useMemo(() => [
    { label: '目录条目总数', value: total },
    { label: '已发布条目', value: rows.filter((row) => row.status === '已发布').length },
    { label: '已下线条目', value: rows.filter((row) => row.status === '已下线').length },
  ], [rows, total])

  return (
    <section className="page" data-module="catalog">
      <header className="page-head">
        <div>
          <h2>数据目录检索管理</h2>
          <p className="page-desc">维护数据目录的业务域归属、字段清单与等级标识，为数据目录检索提供可追溯的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('目录条目登记入口尚未接入审批流')}>
            登记目录条目
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出数据目录检索清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>字段清单</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <Fragment key={String(row.id)}>
              <tr>
                {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
                <td>
                  <button className="link" type="button" onClick={() => setExpanded((prev) => (prev === row.id ? null : Number(row.id)))}>
                    {row.字段数 ?? 0} 个字段（{expanded === row.id ? '收起' : '展开'}）
                  </button>
                </td>
                <td className="row-actions">
                  {row.readonly ? (
                    <span className="muted-text">只读</span>
                  ) : (
                    actions.map((action) => (
                      <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                        {action}
                      </button>
                    ))
                  )}
                </td>
              </tr>
              {expanded === row.id && (
                <tr>
                  <td colSpan={columns.length + 2}>
                    <p className="muted-text">{row.字段清单来源}</p>
                    <ul className="plain-list">
                      {(row.字段清单 ?? []).map((field) => (
                        <li key={field.字段名}>
                          <code>{field.字段名}</code> · {field.类型} · {field.说明}
                        </li>
                      ))}
                      {(row.字段清单 ?? []).length === 0 && <li className="muted-text">未关联共用字段清单</li>}
                    </ul>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 2}>暂无数据目录检索数据，可先登记目录条目</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条数据目录检索记录</span>
        {message && <span className="ok-text">{message}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
