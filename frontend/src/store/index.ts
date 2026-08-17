import { configureStore, createSlice, PayloadAction } from '@reduxjs/toolkit'
import type { User, Session } from '../services/api'

// ── Auth Slice ────────────────────────────────────────────

interface AuthState {
  user: User | null
  token: string | null
}

const authSlice = createSlice({
  name: 'auth',
  initialState: {
    user: JSON.parse(localStorage.getItem('user') || 'null'),
    token: localStorage.getItem('token'),
  } as AuthState,
  reducers: {
    setAuth(state, action: PayloadAction<{ user: User; token: string }>) {
      state.user = action.payload.user
      state.token = action.payload.token
      localStorage.setItem('user', JSON.stringify(action.payload.user))
      localStorage.setItem('token', action.payload.token)
    },
    clearAuth(state) {
      state.user = null
      state.token = null
      localStorage.removeItem('user')
      localStorage.removeItem('token')
    },
  },
})

// ── Chat Slice ────────────────────────────────────────────

interface ChatState {
  sessions: Session[]
  currentSessionId: string | null
}

const chatSlice = createSlice({
  name: 'chat',
  initialState: {
    sessions: [],
    currentSessionId: null,
  } as ChatState,
  reducers: {
    setSessions(state, action: PayloadAction<Session[]>) {
      state.sessions = action.payload
    },
    addSession(state, action: PayloadAction<Session>) {
      state.sessions.unshift(action.payload)
      state.currentSessionId = action.payload.id
    },
    removeSession(state, action: PayloadAction<string>) {
      state.sessions = state.sessions.filter(s => s.id !== action.payload)
      if (state.currentSessionId === action.payload) {
        state.currentSessionId = state.sessions[0]?.id || null
      }
    },
    setCurrentSession(state, action: PayloadAction<string>) {
      state.currentSessionId = action.payload
    },
    updateSessionTitle(state, action: PayloadAction<{ id: string; title: string }>) {
      const s = state.sessions.find(s => s.id === action.payload.id)
      if (s) s.title = action.payload.title
    },
  },
})

export const { setAuth, clearAuth } = authSlice.actions
export const { setSessions, addSession, removeSession, setCurrentSession, updateSessionTitle } = chatSlice.actions

export const store = configureStore({
  reducer: {
    auth: authSlice.reducer,
    chat: chatSlice.reducer,
  },
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
