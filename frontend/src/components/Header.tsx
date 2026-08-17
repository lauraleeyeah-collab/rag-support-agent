import React, { useState } from 'react'
import { Layout, Space, Typography, Button, Dropdown, Modal, Form, Input, message } from 'antd'
import { UserOutlined, LogoutOutlined, KeyOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { authApi } from '../services/api'
import { clearAuth } from '../store'
import type { RootState } from '../store'

const { Header: AntHeader } = Layout
const { Text } = Typography

const Header: React.FC = () => {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const user = useSelector((s: RootState) => s.auth.user)
  const [changePwdOpen, setChangePwdOpen] = useState(false)
  const [form] = Form.useForm()

  const handleLogout = () => {
    dispatch(clearAuth())
    navigate('/login')
  }

  const handleChangePwd = async (values: any) => {
    try {
      await authApi.changePassword(values.old_password, values.new_password)
      message.success('密码修改成功，请重新登录')
      setChangePwdOpen(false)
      dispatch(clearAuth())
      navigate('/login')
    } catch (e: any) {
      message.error(e.response?.data?.detail || '修改失败')
    }
  }

  const menuItems = [
    {
      key: 'change-pwd',
      icon: <KeyOutlined />,
      label: '修改密码',
      onClick: () => setChangePwdOpen(true)
    },
    { type: 'divider' as const },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
      onClick: handleLogout
    }
  ]

  return (
    <>
      <AntHeader style={{
        background: '#fff',
        padding: '0 24px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid #f0f0f0',
        height: 56
      }}>
        <Text style={{ fontSize: 15, fontWeight: 500, color: '#333' }}>
          电商智能客服系统
        </Text>

        <Dropdown menu={{ items: menuItems }} placement="bottomRight">
          <Button type="text" icon={<UserOutlined />} style={{ color: '#555' }}>
            {user?.username}
            {user?.role === 'admin' && (
              <Text style={{ fontSize: 11, color: '#7c6af7', marginLeft: 4 }}>管理员</Text>
            )}
          </Button>
        </Dropdown>
      </AntHeader>

      <Modal
        title="修改密码"
        open={changePwdOpen}
        onCancel={() => setChangePwdOpen(false)}
        footer={null}
      >
        <Form form={form} onFinish={handleChangePwd} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="old_password" label="原密码" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 6 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" rules={[
            { required: true },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                return Promise.reject('两次密码不一致')
              }
            })
          ]}>
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>确认修改</Button>
        </Form>
      </Modal>
    </>
  )
}

export default Header
