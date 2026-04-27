# ofd2html

OFD → HTML 转换服务，基于 FastAPI。仅支持 OFD 到 HTML 的渲染（签章/PDF/图片导出等不在范围内）。

## 在线使用

[点击跳转](https://nullying.github.io/ofd2html-python/)

## 安装（开发）

本项目使用 [uv](https://docs.astral.sh/uv/) 作为包管理器：

```bash
uv sync --extra dev   # 创建 .venv 并安装依赖（含开发依赖）
```

## 启动服务

```bash
uv run uvicorn ofd2html.api.app:app --host 0.0.0.0 --port 8000
```

## API

- `GET /health` → `{"code": 200, "msg": "ok"}`
- `POST /ofd/convert?task_id=<id>`（multipart/form-data，字段名 `file`）

  响应体：

  ```json
  {
    "code": 200,
    "msg": "ok",
    "task_id": "<echoed>",
    "data": "<!DOCTYPE html>..."
  }
  ```

  HTTP 状态码恒为 200，业务状态在 `code` 字段中
  （`200` 成功 / `400` 输入错误 / `504` 超时 / `500` 内部错误）。

  调用方示例：

  ```python
  resp = requests.post(
      f"http://{host}:{port}/ofd/convert",
      params={"task_id": task_id},
      files=[("file", ("invoice.ofd", file_obj, "application/octet-stream"))],
      timeout=5,
  )
  data = resp.json()
  if data.get("code", 0) == 200:
      html = data["data"]
  ```

## 配置

| 环境变量              | 默认值              | 说明             |
| --------------------- | ------------------- | ---------------- |
| `OFD_MAX_BYTES`       | `20971520` (20 MiB) | 上传文件大小上限 |
| `OFD_CONVERT_TIMEOUT` | `4.5`（秒）         | 单次转换的硬超时 |

## 测试

```bash
uv run pytest
```

集成用例会自动遍历仓库根目录 `tests_ofd/` 下的全部 `*.ofd` 样本。

## 致谢

本项目对 OFD 规范（GB/T 33190-2016）格式细节的理解，得益于开源项目
[ofdrw](https://github.com/ofdrw/ofdrw) 的长期实践与文档积累。
特此向 ofdrw 项目及其贡献者致谢。
