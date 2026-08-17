import React, { useState, useEffect, useRef } from 'react'
import {
  Input, Button, Typography, Spin, Empty, Tag, Collapse,
  message as antdMessage
} from 'antd'
import { SendOutlined, LoadingOutlined } from '@ant-design/icons'
import { useSelector } from 'react-redux'
import { chatApi, type Message, type Citation, type TriageAction } from '../services/api'
import type { RootState } from '../store'

const { Text, Paragraph } = Typography

// ── 分诊标签配置（R7，文案/配色与后端 constants.py 约定一致）──────
const TRIAGE_TAG_CONFIG: Record<TriageAction, { text: string; color: string; bg: string }> = {
  direct: { text: '直接回答', color: '#fff', bg: '#2e7d32' },      // 🟢 绿底白字
  cautious: { text: '谨慎回答', color: '#333', bg: '#f9a825' },    // 🟡 黄底深字
  human: { text: '已转人工', color: '#fff', bg: '#c62828' },       // 🔴 红底白字
  refusal: { text: '暂时无法确认', color: '#fff', bg: '#616161' }, // ⚪ 灰底白字
}

// 谨慎回答尾缀标记（与后端 CAUTIOUS_SUFFIX 对应，用于拆分正文与尾注）
const CAUTIOUS_SUFFIX_MARK = '⚠️ 以上信息仅供参考'

// 分诊胶囊标签（R7）：AI 消息气泡上方
const TriageTag: React.FC<{ action: TriageAction }> = ({ action }) => {
  const cfg = TRIAGE_TAG_CONFIG[action]
  if (!cfg) return null
  return (
    <div style={{ marginBottom: 6 }}>
      <span style={{
        display: 'inline-block',
        padding: '2px 10px',
        borderRadius: 12,
        fontSize: 12,
        fontWeight: 500,
        color: cfg.color,
        background: cfg.bg,
      }}>
        {cfg.text}
      </span>
    </div>
  )
}

// 转人工提示条（R8）：红色醒目横幅，不显示 AI 答案区
const HumanBanner: React.FC<{ text: string }> = ({ text }) => (
  <div style={{
    background: '#fdecea',
    borderLeft: '4px solid #c62828',
    borderRadius: 6,
    padding: '12px 16px',
  }}>
    <div style={{ color: '#c62828', fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
      ⚠️ 已为您转接人工客服
    </div>
    <div style={{ color: '#b71c1c', fontSize: 13, lineHeight: 1.6 }}>
      {text}
    </div>
  </div>
)

const CitationCard: React.FC<{ citations: Citation[] }> = ({ citations }) => (
  <Collapse
    size="small"
    style={{ marginTop: 8, background: '#f6ffed', border: '1px solid #b7eb8f' }}
    items={[{
      key: '1',
      label: <Text style={{ fontSize: 12, color: '#52c41a' }}>引用了 {citations.length} 个知识库片段</Text>,
      children: citations.map((c, i) => (
        <div key={i} style={{
          padding: '8px 12px', marginBottom: 8,
          background: '#fff', borderRadius: 6,
          border: '1px solid #e8e8e8', fontSize: 13
        }}>
          <Tag color="green" style={{ marginBottom: 4 }}>{c.source}</Tag>
          <Paragraph style={{ margin: 0, fontSize: 12, color: '#555' }}>{c.content}</Paragraph>
        </div>
      ))
    }]}
  />
)

const MessageBubble: React.FC<{ msg: Message }> = ({ msg }) => {
  const isUser = msg.role === 'user'
  const action = msg.triage_action

  // AI 消息按分诊动作渲染不同形态（历史消息 action 为空 → 普通气泡，不渲染标签）
  const renderAssistantContent = () => {
    // R8：转人工 → 红色横幅，不显示 AI 答案区
    if (action === 'human') {
      return <HumanBanner text={msg.content} />
    }

    // R9：谨慎回答 → 正文 + 分隔线 + 灰字尾注
    if (action === 'cautious' && msg.content.includes(CAUTIOUS_SUFFIX_MARK)) {
      const sepIndex = msg.content.lastIndexOf('---')
      const body = sepIndex > 0 ? msg.content.slice(0, sepIndex).trimEnd() : msg.content
      const suffix = msg.content.slice(msg.content.indexOf(CAUTIOUS_SUFFIX_MARK))
      return (
        <div style={{
          padding: '10px 16px',
          borderRadius: '18px 18px 18px 4px',
          background: '#f5f5f5',
          color: '#333',
          fontSize: 14,
          lineHeight: 1.6,
          wordBreak: 'break-word'
        }}>
          <div style={{ whiteSpace: 'pre-wrap' }}>{body}</div>
          <div style={{ borderTop: '1px solid #e0e0e0', margin: '10px 0 8px' }} />
          <div style={{ color: '#757575', fontSize: 12, fontStyle: 'italic' }}>{suffix}</div>
        </div>
      )
    }

    // 默认气泡（direct / refusal / 历史无标签消息）
    return (
      <div style={{
        padding: '10px 16px',
        borderRadius: '18px 18px 18px 4px',
        background: '#f5f5f5',
        color: '#333',
        fontSize: 14,
        lineHeight: 1.6,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word'
      }}>
        {msg.content}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 16 }}>
      <div style={{ maxWidth: '75%' }}>
        {!isUser && action && <TriageTag action={action} />}
        {isUser ? (
          <div style={{
            padding: '10px 16px',
            borderRadius: '18px 18px 4px 18px',
            background: '#1677ff',
            color: '#fff',
            fontSize: 14,
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word'
          }}>
            {msg.content}
          </div>
        ) : renderAssistantContent()}
        {!isUser && msg.citations && msg.citations.length > 0 && (
          <CitationCard citations={msg.citations} />
        )}
      </div>
    </div>
  )
}

const Chat: React.FC = () => {
  const currentSessionId = useSelector((s: RootState) => s.chat.currentSessionId)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [fetching, setFetching] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!currentSessionId) {
      setMessages([])
      return
    }
    setFetching(true)
    chatApi.getMessages(currentSessionId)
      .then(res => setMessages(res.data))
      .catch(() => antdMessage.error('加载消息失败'))
      .finally(() => setFetching(false))
  }, [currentSessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || !currentSessionId || loading) return
    const question = input.trim()
    setInput('')

    // 乐观更新：先显示用户消息
    const tempUserMsg: Message = {
      id: 'temp-user',
      role: 'user',
      content: question,
      created_at: new Date().toISOString()
    }
    setMessages(prev => [...prev, tempUserMsg])
    setLoading(true)

    try {
      const res = await chatApi.ask(currentSessionId, question)
      const aiMsg: Message = {
        id: res.data.message_id,
        role: 'assistant',
        content: res.data.answer,
        citations: res.data.citations,
        triage_type: res.data.triage_type,
        triage_action: res.data.triage_action,
        created_at: new Date().toISOString()
      }
      setMessages(prev => [...prev, aiMsg])
    } catch (e: any) {
      antdMessage.error(e.response?.data?.detail || '回答失败，请重试')
      setMessages(prev => prev.filter(m => m.id !== 'temp-user'))
    } finally {
      setLoading(false)
    }
  }

  if (!currentSessionId) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="请在左侧选择或新建一个对话" />
      </div>
    )
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 消息区域 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
        {fetching ? (
          <div style={{ textAlign: 'center', paddingTop: 40 }}>
            <Spin indicator={<LoadingOutlined spin />} />
          </div>
        ) : messages.length === 0 ? (
          <Empty description="发送消息开始对话" style={{ paddingTop: 60 }} />
        ) : (
          messages.map(msg => <MessageBubble key={msg.id} msg={msg} />)
        )}
        {loading && (
          <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: 16 }}>
            <div style={{
              padding: '10px 16px', borderRadius: '18px 18px 18px 4px',
              background: '#f5f5f5', color: '#999', fontSize: 14
            }}>
              <Spin size="small" style={{ marginRight: 8 }} />
              正在思考中...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 输入区域 */}
      <div style={{
        padding: '12px 24px',
        borderTop: '1px solid #f0f0f0',
        background: '#fff',
        display: 'flex',
        gap: 12
      }}>
        <Input.TextArea
          value={input}
          onChange={e => setInput(e.target.value)}
          onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }}
          placeholder="输入问题，按 Enter 发送，Shift+Enter 换行"
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={loading}
          style={{ borderRadius: 8 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          loading={loading}
          style={{ height: 'auto', borderRadius: 8 }}
        >
          发送
        </Button>
      </div>
    </div>
  )
}

export default Chat
