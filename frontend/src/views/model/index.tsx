import { useCallback, useEffect, useMemo, useState } from 'react'

import { readActionMessage, request } from '@/api/client'

const ENDPOINT = '/api/model'
const columns = [
  "模型编号",
  "模型名称",
  "模型类型",
  "训练数据",
  "评估指标",
  "模型版本",
  "部署路径",
  "模型状态",
  "负责人"
]
const actions = [
  "部署模型",
  "下线模型",
  "归档模型"
]
const statuses = [
  "草稿",
  "训练完成",
  "已部署",
  "已下线",
  "已归档"
]

type FieldDef = { 字段名: string; 类型: string; 说明: string }
type TrainingBlock = {
  数据集编号: string
  数据集名称: string
  字段清单: FieldDef[]
  字段数: number
  引用状态: string
}
type RegistryVersion = {
  记录ID: number
  模型版本: string
  评估指标: string
  模型状态: string
  是否生效: boolean
  部署路径: string
  预检结论: string
  预检说明: string
}
type RegistryModel = {
  模型编号: string
  模型名称: string
  模型类型: string
  负责人: string
  训练数据: TrainingBlock
  版本列表: RegistryVersion[]
}
type RegistryPayload = {
  清单口径: string
  items: RegistryModel[]
}
type PrecheckPayload = {
  模型编号: string
  模型版本: string
  模型类型: string
  训练数据: TrainingBlock
  评估指标: Record<string, number>
  评估指标快照: string
  结论: string
  拒绝原因: string[]
  缺失证据: string[]
  通过项: string[]
}
type DeploymentRecord = {
  记录编号: string
  模型编号: string
  模型版本: string
  执行人: string
  归属负责人: string
  评估指标快照: string
  结果: string
  回退说明?: string
  时间: string
}

type Row = Record<string, string | number | boolean | null | undefined> & {
  字段清单?: FieldDef[]
  可执行动作?: string[]
  readonly?: boolean
  只读说明?: string
  部署预检结论?: string
  部署预检说明?: string
}

const conclusionClass: Record<string, string> = {
  '可部署': 'tag ok',
  '需补充证据': 'tag warn',
  '拒绝部署': 'tag danger',
}

export default function ModelView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [registry, setRegistry] = useState<RegistryPayload | null>(null)
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([])
  const [precheck, setPrecheck] = useState<PrecheckPayload | null>(null)
  const [selected, setSelected] = useState<Row | null>(null)
  const [message, setMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [showRegister, setShowRegister] = useState(false)
  const [register, setRegister] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('模型注册列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)

      const registryResponse = await request(`${ENDPOINT}/registry`)
      if (registryResponse.ok) {
        setRegistry(await registryResponse.json())
      }
      const deploymentResponse = await request(`${ENDPOINT}/deployments`)
      if (deploymentResponse.ok) {
        const payload = await deploymentResponse.json()
        setDeployments(payload.items ?? [])
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析模型沉淀列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
    function onIdentity() {
      void reload()
      setPrecheck(null)
    }
    window.addEventListener('identity-changed', onIdentity)
    return () => window.removeEventListener('identity-changed', onIdentity)
  }, [reload])

  async function runAction(action: string, row: Row) {
    setMessage('')
    setErrorMessage('')
    try {
      const payload: Record<string, unknown> = { action }
      if (action === '变更归属') {
        const owner = window.prompt('请输入新的归属负责人')
        if (!owner) return
        payload.负责人 = owner
      }
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: payload }),
      })
      const text = await readActionMessage(response, '分析模型沉淀动作未生效，请稍后重试')
      if (!response.ok) {
        throw new Error(text)
      }
      setMessage(text)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析模型沉淀操作失败')
    }
  }

  async function showPrecheck(row: Row) {
    setSelected(row)
    setMessage('')
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/precheck`)
      if (!response.ok) {
        throw new Error(await readActionMessage(response, '部署预检读取失败'))
      }
      setPrecheck(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '部署预检读取失败')
    }
  }

  async function submitRegister() {
    setMessage('')
    setErrorMessage('')
    try {
      const response = await request(ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ values: register }),
      })
      const text = await readActionMessage(response, '模型注册登记失败')
      if (!response.ok) {
        throw new Error(text)
      }
      setMessage(text)
      setShowRegister(false)
      setRegister({})
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '模型注册登记失败')
    }
  }

  const stats = useMemo(() => [
    { label: '模型注册总数', value: total },
    { label: '已部署模型', value: rows.filter((row) => row.status === '已部署').length },
    { label: '待补充证据', value: rows.filter((row) => row.部署预检结论 === '需补充证据').length },
    { label: '拒绝部署', value: rows.filter((row) => row.部署预检结论 === '拒绝部署').length },
  ], [rows, total])

  const activeRow = selected

  return (
    <section className="page" data-module="model">
      <header className="page-head">
        <div>
          <h2>分析模型沉淀管理</h2>
          <p className="page-desc">
            按训练数据、评估指标与模型版本生成模型注册清单；部署前先做预检，给出可部署、需补充证据或拒绝部署的结论。
            训练数据字段清单与数据目录检索共用同一份定义。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setShowRegister((prev) => !prev)}>
            {showRegister ? '收起登记表单' : '登记模型注册'}
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出分析模型沉淀清单
          </button>
        </div>
      </header>

      {showRegister && (
        <section className="panel">
          <header className="panel-head">
            <h3>登记模型注册</h3>
            <span className="muted-text">同一模型编号 + 模型版本重复登记只保留一份记录</span>
          </header>
          <div className="filter-bar">
            {[
              ['模型编号', '如 MODE-0004'],
              ['模型名称', '如 客户流失预警模型'],
              ['模型类型', '分类 / 回归 / 聚类'],
              ['训练数据', '如 DS-CUSTOMER-001'],
              ['评估指标', '如 AUC=0.92;准确率=0.90'],
              ['模型版本', '如 v1.2.0'],
              ['部署路径', '如 /models/mode-0004/v1.2.0'],
            ].map(([field, placeholder]) => (
              <label key={field} className="filter-item">
                <span>{field}</span>
                <input
                  value={register[field] ?? ''}
                  placeholder={placeholder}
                  onChange={(event) => setRegister((prev) => ({ ...prev, [field]: event.target.value }))}
                />
              </label>
            ))}
            <label className="filter-item">
              <span>模型状态</span>
              <select
                value={register['模型状态'] ?? '训练完成'}
                onChange={(event) => setRegister((prev) => ({ ...prev, 模型状态: event.target.value }))}
              >
                {statuses.filter((status) => status !== '已归档').map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
            </label>
            <button className="btn primary" type="button" onClick={() => void submitRegister()}>提交登记</button>
          </div>
        </section>
      )}

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
        <label className="filter-item">
          <span>模型状态</span>
          <select
            value={filters.status ?? ''}
            onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
          >
            <option value="">全部</option>
            {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>部署预检</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const conclusion = String(row.部署预检结论 ?? '')
            const allowed = (row.可执行动作 as string[] | undefined) ?? []
            return (
              <tr key={String(row.id)}>
                {columns.map((column) => (
                  <td key={column}>
                    {column === '训练数据'
                      ? `${row[column] ?? '—'}${row.字段清单 ? `（${row.字段清单.length} 字段）` : ''}`
                      : String(row[column] ?? '—')}
                  </td>
                ))}
                <td>
                  <span className={conclusionClass[conclusion] ?? 'tag'}>{conclusion || '—'}</span>
                  <button className="link" type="button" onClick={() => void showPrecheck(row)}>查看依据</button>
                </td>
                <td className="row-actions">
                  {row.readonly && <span className="muted-text">只读</span>}
                  {!row.readonly && allowed.length === 0 && (
                    <span className="muted-text">预检未通过，暂无可执行动作</span>
                  )}
                  {actions.filter((action) => allowed.includes(action)).map((action) => (
                    <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                      {action}
                    </button>
                  ))}
                  {allowed.includes('变更归属') && (
                    <button className="link" type="button" onClick={() => void runAction('变更归属', row)}>
                      变更归属
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 2}>暂无分析模型沉淀数据，可先登记模型注册</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条分析模型沉淀记录</span>
        {message && <span className="ok-text">{message}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      {precheck && activeRow && (
        <section className="panel">
          <header className="panel-head">
            <h3>部署预检 · {precheck.模型编号}/{precheck.模型版本}</h3>
            <span className={conclusionClass[precheck.结论] ?? 'tag'}>{precheck.结论}</span>
            <button className="link" type="button" onClick={() => { setPrecheck(null); setSelected(null) }}>关闭</button>
          </header>
          <div className="panel-grid">
            <div>
              <h4>训练数据与字段清单</h4>
              <p className="muted-text">
                {precheck.训练数据.数据集编号 || '—'} · {precheck.训练数据.数据集名称 || '未登记'}
                （{precheck.训练数据.引用状态}）
              </p>
              <ul className="plain-list">
                {precheck.训练数据.字段清单.map((field) => (
                  <li key={field.字段名}>
                    <code>{field.字段名}</code> · {field.类型} · {field.说明}
                  </li>
                ))}
                {precheck.训练数据.字段清单.length === 0 && <li className="muted-text">未关联共用字段清单</li>}
              </ul>
            </div>
            <div>
              <h4>评估指标</h4>
              <ul className="plain-list">
                {Object.entries(precheck.评估指标).map(([key, value]) => (
                  <li key={key}>{key} = {value}</li>
                ))}
                {Object.keys(precheck.评估指标).length === 0 && <li className="muted-text">未提供可解析的评估指标</li>}
              </ul>
              <p className="muted-text">上一份评估指标快照：{precheck.评估指标快照 || '暂无'}</p>
            </div>
          </div>
          {precheck.拒绝原因.length > 0 && (
            <p className="error-text">拒绝原因：{precheck.拒绝原因.join('；')}</p>
          )}
          {precheck.缺失证据.length > 0 && (
            <p className="warn-text">缺失证据：{precheck.缺失证据.join('；')}</p>
          )}
          {precheck.通过项.length > 0 && (
            <p className="ok-text">通过项：{precheck.通过项.join('；')}</p>
          )}
        </section>
      )}

      <section className="panel">
        <header className="panel-head">
          <h3>模型注册清单</h3>
          <span className="muted-text">{registry?.清单口径 ?? '按训练数据、评估指标与模型版本生成'}</span>
        </header>
        <table className="data-table">
          <thead>
            <tr>
              <th>模型编号</th><th>模型类型</th><th>负责人</th><th>训练数据</th>
              <th>版本</th><th>评估指标</th><th>状态</th><th>是否生效</th><th>预检结论</th>
            </tr>
          </thead>
          <tbody>
            {(registry?.items ?? []).flatMap((model) => model.版本列表.map((version) => (
              <tr key={`${model.模型编号}-${version.模型版本}`}>
                <td>{model.模型编号}</td>
                <td>{model.模型类型}</td>
                <td>{model.负责人 ?? '—'}</td>
                <td>{model.训练数据.数据集编号 || '—'}（{model.训练数据.字段数} 字段）</td>
                <td>{version.模型版本}</td>
                <td>{version.评估指标 || '—'}</td>
                <td>{version.模型状态}</td>
                <td>{version.是否生效 ? '生效中' : '未生效'}</td>
                <td>
                  <span className={conclusionClass[version.预检结论] ?? 'tag'}>{version.预检结论}</span>
                  <span className="muted-text"> {version.预检说明}</span>
                </td>
              </tr>
            )))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <header className="panel-head">
          <h3>发布流水</h3>
          <span className="muted-text">归属变更后历史记录仍按原责任人留档</span>
        </header>
        <table className="data-table">
          <thead>
            <tr>
              <th>记录编号</th><th>模型编号</th><th>模型版本</th><th>执行人</th>
              <th>归属负责人</th><th>评估指标快照</th><th>结果</th><th>说明</th><th>时间</th>
            </tr>
          </thead>
          <tbody>
            {deployments.map((record) => (
              <tr key={record.记录编号}>
                <td>{record.记录编号}</td>
                <td>{record.模型编号}</td>
                <td>{record.模型版本}</td>
                <td>{record.执行人}</td>
                <td>{record.归属负责人}</td>
                <td>{record.评估指标快照}</td>
                <td>{record.结果}</td>
                <td>{record.回退说明 ?? '—'}</td>
                <td>{record.时间}</td>
              </tr>
            ))}
            {deployments.length === 0 && (
              <tr><td className="empty-state" colSpan={9}>暂无发布流水</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </section>
  )
}
