# -*- coding: utf-8 -*-
"""pytest 共享配置：路径与重依赖 stub。

单元测试目标：
- 不依赖 LLM（dashscope）、ChromaDB、网络、数据库。
- triage_rules / constants 为纯函数，直接可测。
- rag_service 的拒答短路逻辑通过 stub 掉 dashscope / doc_service 后导入，
  再 monkeypatch 检索层与分诊层，验证「低于阈值不调 LLM、直接返回拒答常量」。
- run_eval.judge 的判定口径测试通过 stub `requests` 后导入评测脚本。

注意：stub 必须在**模块导入期**（conftest 顶层）完成，而非 fixture 中——
因为被测模块在 pytest collection 阶段就会执行顶层 import，此时 fixture 尚未运行。
"""

import os
import sys
import types

# ── 路径设置：让 `import app.xxx` 与 `import run_eval` 可用 ──────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
EVAL_DIR = os.path.join(PROJECT_ROOT, "eval")

for _p in (BACKEND_DIR, EVAL_DIR, PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _make_module(name: str, **attrs) -> types.ModuleType:
    """创建并注册一个模块到 sys.modules（仅当真实库缺失时才应调用）。"""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _install_stubs() -> None:
    """为缺失的第三方库安装轻量 stub（已安装的真实库不受影响）。"""

    # dashscope：rag_service / triage_service 顶层 `import dashscope` 并设置 api_key
    try:
        import dashscope  # noqa: F401
    except Exception:
        class _Generation:
            @staticmethod
            def call(*args, **kwargs):  # pragma: no cover - 防御
                raise RuntimeError("dashscope 已被 stub，单测不应触发真实 LLM 调用")

        ds = _make_module("dashscope")
        ds.api_key = None
        ds.Generation = _Generation
        # 兼容 `from dashscope import Generation`
        gen_mod = _make_module("dashscope.Generation")
        gen_mod.Generation = _Generation

    # requests：eval/run_eval.py 顶层 import requests
    try:
        import requests  # noqa: F401
    except Exception:
        class _Session:
            def __init__(self, *a, **k):
                self.headers = {}

            def post(self, *a, **k):  # pragma: no cover - 判定测试不发请求
                raise RuntimeError("requests 已被 stub，判定口径单测不应发真实请求")

        _make_module("requests", Session=_Session)


_install_stubs()
