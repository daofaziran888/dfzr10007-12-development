/** 统一请求封装：拼后端地址、抛网络错误、给页脚留一句可读的说明。
 *
 * 平台未接登录，当前值班身份由页面顶部选择；请求头带上 X-Operator / X-Role，
 * 后端据此判断模型部署权限。HTTP 头只保证 ASCII，中文身份按 URL 编码传输。
 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export type Identity = {
  operator: string
  role: string
}

const IDENTITY_STORAGE_KEY = 'insight.identity'
const DEFAULT_IDENTITY: Identity = { operator: '赵启明', role: '模型负责人' }

let identity: Identity = loadIdentity()

function loadIdentity(): Identity {
  try {
    const raw = window.localStorage.getItem(IDENTITY_STORAGE_KEY)
    if (!raw) return DEFAULT_IDENTITY
    const parsed = JSON.parse(raw) as Partial<Identity>
    return {
      operator: String(parsed.operator || DEFAULT_IDENTITY.operator),
      role: String(parsed.role || DEFAULT_IDENTITY.role),
    }
  } catch {
    return DEFAULT_IDENTITY
  }
}

export function getIdentity(): Identity {
  return identity
}

export function setIdentity(next: Identity): void {
  identity = next
  try {
    window.localStorage.setItem(IDENTITY_STORAGE_KEY, JSON.stringify(next))
  } catch {
    // 隐私模式下写不了本地存储，保持内存态即可
  }
}

function identityHeaders(): Record<string, string> {
  return {
    'X-Operator': encodeURIComponent(identity.operator),
    'X-Role': encodeURIComponent(identity.role),
  }
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...identityHeaders(),
      ...(init?.headers ?? {}),
    },
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/** 动作接口无论成功失败都返回一句说明：优先用后端 detail，其次用 message。 */
export async function readActionMessage(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => null)) as
    | { detail?: string; message?: string }
    | null
  return payload?.detail || payload?.message || fallback
}
