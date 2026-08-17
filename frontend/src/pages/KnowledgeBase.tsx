import React, { useState, useEffect } from 'react'
import {
  Table, Button, Upload, Tag, Space, Popconfirm,
  message, Typography, Progress, Card
} from 'antd'
import { UploadOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { knowledgeApi, type Document } from '../services/api'

const { Title, Text } = Typography

const statusMap: Record<string, { color: string; label: string }> = {
  processing: { color: 'processing', label: '处理中' },
  ready: { color: 'success', label: '已就绪' },
  failed: { color: 'error', label: '失败' },
}

const KnowledgeBase: React.FC = () => {
  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)

  const fetchDocs = async () => {
    setLoading(true)
    try {
      const res = await knowledgeApi.getDocuments()
      setDocs(res.data)
    } catch {
      message.error('加载文档列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocs()
    // 有处理中的文档时，每 5 秒刷新一次
    const timer = setInterval(() => {
      if (docs.some(d => d.status === 'processing')) fetchDocs()
    }, 5000)
    return () => clearInterval(timer)
  }, [docs.length])

  const handleUpload = async (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'docx', 'txt', 'md'].includes(ext || '')) {
      message.error('仅支持 PDF、DOCX、TXT、MD 格式')
      return false
    }
    setUploading(true)
    setUploadProgress(0)
    try {
      const res = await knowledgeApi.uploadDocument(file, setUploadProgress)
      setDocs(prev => [res.data, ...prev])
      message.success('上传成功，正在后台处理...')
    } catch (e: any) {
      message.error(e.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
    return false // 阻止 antd 默认上传行为
  }

  const handleDelete = async (id: string) => {
    try {
      await knowledgeApi.deleteDocument(id)
      setDocs(prev => prev.filter(d => d.id !== id))
      message.success('删除成功')
    } catch {
      message.error('删除失败')
    }
  }

  const columns = [
    {
      title: '文件名',
      dataIndex: 'original_filename',
      key: 'filename',
      render: (name: string) => <Text strong>{name}</Text>
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'size',
      render: (size: number) => `${(size / 1024).toFixed(1)} KB`
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const s = statusMap[status] || { color: 'default', label: status }
        return <Tag color={s.color}>{s.label}</Tag>
      }
    },
    {
      title: '切片数',
      dataIndex: 'chunk_count',
      key: 'chunks',
      render: (n: number) => n > 0 ? `${n} 个片段` : '-'
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'time',
      render: (t: string) => new Date(t).toLocaleString('zh-CN')
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Document) => (
        <Popconfirm
          title="确认删除此文档？"
          description="删除后将同步清除知识库中的相关内容"
          onConfirm={() => handleDelete(record.id)}
          okText="确认"
          cancelText="取消"
        >
          <Button danger icon={<DeleteOutlined />} size="small">删除</Button>
        </Popconfirm>
      )
    }
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>知识库管理</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchDocs}>刷新</Button>
          <Upload beforeUpload={handleUpload} showUploadList={false} accept=".pdf,.docx,.txt,.md">
            <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
              上传文档
            </Button>
          </Upload>
        </Space>
      </div>

      {uploading && (
        <Card style={{ marginBottom: 16 }}>
          <Text>正在上传...</Text>
          <Progress percent={uploadProgress} style={{ marginTop: 8 }} />
        </Card>
      )}

      <Card>
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          支持格式：PDF、Word (.docx)、TXT、Markdown。上传后系统自动处理，处理完成后即可用于问答。
        </Text>
        <Table
          columns={columns}
          dataSource={docs}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10 }}
          locale={{ emptyText: '暂无文档，请上传知识库文件' }}
        />
      </Card>
    </div>
  )
}

export default KnowledgeBase
