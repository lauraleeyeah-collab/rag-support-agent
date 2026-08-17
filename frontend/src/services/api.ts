import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

// 自动带上 token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 401 自动跳登录
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api

// ── 类型定义 ──────────────────────────────────────────────

export interface User {
  id: string
  username: string
  role: string
  created_at: string
}

export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Citation {
  content: string
  source: string
}

// 分诊动作枚举（与后端 constants.py 保持一致）
export type TriageAction = 'direct' | 'cautious' | 'human' | 'refusal'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  // 客服分诊增量：分诊字段（历史消息为 null/undefined，不渲染标签）
  triage_type?: string | null
  triage_action?: TriageAction | null
  created_at: string
}

export interface ChatResponse {
  message_id: string
  answer: string
  citations: Citation[]
  triage_type?: string | null
  triage_action?: TriageAction | null
  retrieved_sources?: string[]
}

export interface Document {
  id: string
  original_filename: string
  file_size: number
  status: 'processing' | 'ready' | 'failed'
  chunk_count: number
  error_message?: string
  created_at: string
}

// ── Auth ─────────────────────────────────────────────────

export const authApi = {
  register: (username: string, password: string) =>
    api.post('/auth/register', { username, password }),
  login: (username: string, password: string) =>
    api.post('/auth/login', { username, password }),
  changePassword: (old_password: string, new_password: string) =>
    api.post('/auth/change-password', { old_password, new_password }),
  me: () => api.get<User>('/auth/me'),
}

// ── Chat ─────────────────────────────────────────────────

export const chatApi = {
  getSessions: () => api.get<Session[]>('/chat/sessions'),
  createSession: (title?: string) =>
    api.post<Session>('/chat/sessions', { title: title || '新对话' }),
  deleteSession: (id: string) => api.delete(`/chat/sessions/${id}`),
  getMessages: (sessionId: string) =>
    api.get<Message[]>(`/chat/sessions/${sessionId}/messages`),
  ask: (session_id: string, question: string) =>
    api.post<ChatResponse>('/chat/ask', { session_id, question }),
}

// ── Knowledge ────────────────────────────────────────────

export const knowledgeApi = {
  getDocuments: () => api.get<Document[]>('/knowledge/documents'),
  uploadDocument: (file: File, onProgress?: (pct: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<Document>('/knowledge/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
      },
    })
  },
  deleteDocument: (id: string) => api.delete(`/knowledge/documents/${id}`),
}
