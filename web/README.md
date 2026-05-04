# DocWise Web

DocWise 的 Next.js 前端控制台，覆盖对话、文档、链路、评估和检索实验室。

```powershell
$env:DOCWISE_API_PROXY_TARGET="http://127.0.0.1:8000"
$env:NEXT_PUBLIC_DOCWISE_API_BASE_URL="/api/v1"
npm run dev
```

浏览器访问 `http://localhost:3000`。前端默认通过 Next.js 同源代理转发到后端，后端 `CORS_ORIGINS` 需要包含 `http://localhost:3000` 与 `http://127.0.0.1:3000`。

主要后端依赖：

- `POST /api/v1/chat/stream`
- `GET /api/v1/chat/conversations`
- `GET /api/v1/documents`
- `GET /api/v1/traces`
- `GET /api/v1/eval/trends`
- `POST /api/v1/lab/compare`
