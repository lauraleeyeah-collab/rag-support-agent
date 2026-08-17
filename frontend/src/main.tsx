import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { store } from './store'
import App from './App'
import './index.css'

const root = createRoot(document.getElementById('root')!)
root.render(
  <Provider store={store}>
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#7c6af7' } }}>
      <App />
    </ConfigProvider>
  </Provider>
)
