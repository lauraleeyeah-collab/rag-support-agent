import React from 'react'
import { createBrowserRouter, RouterProvider, Navigate, Outlet } from 'react-router-dom'
import { Layout } from 'antd'
import { useSelector } from 'react-redux'
import Header from './components/Header'
import Sidebar from './components/Sidebar'
import Login from './pages/Login'
import Chat from './pages/Chat'
import KnowledgeBase from './pages/KnowledgeBase'
import type { RootState } from './store'

// 需要登录才能访问的页面
const ProtectedLayout: React.FC = () => {
  const token = useSelector((s: RootState) => s.auth.token)
  if (!token) return <Navigate to="/login" replace />

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sidebar />
      <Layout>
        <Header />
        <Layout.Content style={{ background: '#fafafa', height: 'calc(100vh - 56px)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  )
}

// 管理员才能访问的页面
const AdminRoute: React.FC = () => {
  const user = useSelector((s: RootState) => s.auth.user)
  if (user?.role !== 'admin') return <Navigate to="/" replace />
  return <Outlet />
}

const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />
  },
  {
    path: '/',
    element: <ProtectedLayout />,
    children: [
      { index: true, element: <Chat /> },
      {
        path: 'knowledge',
        element: <AdminRoute />,
        children: [
          { index: true, element: <KnowledgeBase /> }
        ]
      }
    ]
  }
])

const App: React.FC = () => <RouterProvider router={router} />

export default App
