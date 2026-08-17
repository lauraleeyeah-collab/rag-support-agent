import React, { useEffect } from 'react'
import { Layout, Button, List, Typography, Tooltip, Popconfirm, message } from 'antd'
import {
  PlusOutlined, DeleteOutlined, DatabaseOutlined,
  MessageOutlined, CommentOutlined
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { chatApi } from '../services/api'
import {
  setSessions, addSession, removeSession, setCurrentSession
} from '../store'
import type { RootState } from '../store'

const { Sider } = Layout
const { Text } = Typography

const Sidebar: React.FC = () => {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const location = useLocation()
  const { sessions, currentSessionId } = useSelector((s: RootState) => s.chat)
  const user = useSelector((s: RootState) => s.auth.user)

  useEffect(() => {
    if (!user) return
    chatApi.getSessions()
      .then(res => {
        dispatch(setSessions(res.data))
        if (res.data.length > 0 && !currentSessionId) {
          dispatch(setCurrentSession(res.data[0].id))
        }
      })
      .catch(() => {})
  }, [user])

  const handleNewSession = async () => {
    try {
      const res = await chatApi.createSession()
      dispatch(addSession(res.data))
      navigate('/')
    } catch {
      message.error('创建对话失败')
    }
  }

  const handleDeleteSession = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await chatApi.deleteSession(id)
      dispatch(removeSession(id))
    } catch {
      message.error('删除失败')
    }
  }

  return (
    <Sider
      width={240}
      style={{
        background: '#1e1e2e',
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        position: 'sticky',
        top: 0
      }}
    >
      {/* Logo */}
      <div style={{ padding: '20px 16px 12px', borderBottom: '1px solid #2a2a3e' }}>
        <Text style={{ color: '#fff', fontSize: 16, fontWeight: 600 }}>
          💬 知识库问答
        </Text>
      </div>

      {/* 新建对话 */}
      <div style={{ padding: '12px 12px 8px' }}>
        <Button
          type="dashed"
          icon={<PlusOutlined />}
          onClick={handleNewSession}
          block
          style={{ borderColor: '#444', color: '#ccc', background: 'transparent' }}
        >
          新建对话
        </Button>
      </div>

      {/* 会话列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
        <List
          dataSource={sessions}
          renderItem={session => (
            <List.Item
              onClick={() => {
                dispatch(setCurrentSession(session.id))
                navigate('/')
              }}
              style={{
                padding: '8px 12px',
                cursor: 'pointer',
                borderRadius: 8,
                marginBottom: 2,
                background: currentSessionId === session.id ? '#2a2a4e' : 'transparent',
                border: 'none',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                transition: 'background 0.15s'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, overflow: 'hidden' }}>
                <CommentOutlined style={{ color: '#888', flexShrink: 0 }} />
                <Text
                  style={{
                    color: currentSessionId === session.id ? '#fff' : '#bbb',
                    fontSize: 13,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap'
                  }}
                >
                  {session.title}
                </Text>
              </div>
              <Tooltip title="删除">
                <Button
                  type="text"
                  size="small"
                  icon={<DeleteOutlined />}
                  onClick={(e) => handleDeleteSession(session.id, e)}
                  style={{ color: '#666', flexShrink: 0 }}
                />
              </Tooltip>
            </List.Item>
          )}
          locale={{ emptyText: <Text style={{ color: '#555' }}>暂无对话</Text> }}
        />
      </div>

      {/* 管理员入口 */}
      {user?.role === 'admin' && (
        <div style={{ padding: '12px', borderTop: '1px solid #2a2a3e' }}>
          <Button
            type="text"
            icon={<DatabaseOutlined />}
            onClick={() => navigate('/knowledge')}
            block
            style={{
              color: location.pathname === '/knowledge' ? '#7c6af7' : '#888',
              textAlign: 'left'
            }}
          >
            知识库管理
          </Button>
        </div>
      )}
    </Sider>
  )
}

export default Sidebar
