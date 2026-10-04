# Sentinel Auth — Workflow Diagrams (v3.3)

> Tài liệu workflow UML cho architecture v3.3 (3 services, 3 databases, HTTP communication)

## 📁 Cấu trúc files

```
docs/diagrams/
├── README.md                      # File này
├── architecture.uml               # Architecture overview (PlantUML)
├── wf1_login.uml                  # WF-1: Login Flow
├── wf2_detection.uml              # WF-2: Detection Engine Flow
├── wf3_soc.uml                    # WF-3: SOC Alert Workflow
├── wf4_mfa_flow.uml               # WF-4: MFA Flow (chi tiết)
├── wf5_session_management.uml     # WF-5: Session Management
├── wf6_ml_inference.uml           # WF-6: ML Inference (MỚI v3.3)
└── ERD_v3.3.md                    # Database ERD

docs/
└── workflows.mmd                  # Tất cả Mermaid diagrams (master file)
```

## 🔄 Workflows Overview (v3.3)

| ID | Workflow | Service | Actors |
|----|----------|---------|--------|
| WF-1 | Login Flow | core-app | User |
| WF-2 | Detection Engine | detection-engine | System |
| WF-3 | SOC Alert | detection-engine | SOC Analyst |
| WF-4 | MFA Flow | core-app | User |
| WF-5 | Session Management | core-app | User / Admin |
| WF-6 | ML Inference | ml-service | Detection Engine |

## 🚀 Cách sử dụng

### PlantUML (`.uml` files)

**Render trực tuyến:**
- Mở file `.uml` trên [PlantUML Server](https://www.plantuml.com/plantuml/uml/)

**VS Code:**
1. Cài extension "PlantUML"
2. Mở file `.uml`
3. `Alt+D` để preview

**CLI:**
```bash
# Cần có Java + plantuml.jar
java -jar plantuml.jar docs/diagrams/wf1_login.uml
# Output: docs/diagrams/wf1_login.png
```

### Mermaid (file `docs/workflows.mmd`)

**GitHub/GitLab:** Mở file `.mmd` hoặc `.md` chứa code block `mermaid` → render tự động.

**VS Code:**
1. Cài extension "Mermaid Preview"
2. Mở file → `Ctrl+Shift+P` → "Mermaid: Preview"

**CLI:**
```bash
npm install -g @mermaid-js/mermaid-cli
mmdc -i docs/workflows.mmd -o workflows.pdf
```

## 🔑 Thay đổi chính v3.3

### 1. Tách thành 3 services riêng biệt
```
core-app (port 8000)        ← User-facing, auth, MFA, sessions
detection-engine (port 8001) ← Risk detection, SOC workflow
ml-service (port 8002)      ← ML inference (stateless)
```

### 2. Detection chạy ASYNC qua Outbox Pattern
- **Trước (v3.2):** Core gọi detection sync trong request login
- **Sau (v3.3):** Core INSERT `outbox_events` → Poller → HTTP push sang Detection Engine
- Lợi ích: Login không bị block chờ detection

### 3. 3 databases tách biệt
- **core-db:** 13 tables (users, sessions, MFA, outbox)
- **detection-db:** 7 tables (policies, login_attempts, alerts, ...)
- **ml-service-db:** 3 tables (model_versions, inference_logs, feature_stats)

### 4. HTTP communication giữa services
```
Core App ←→ Detection Engine  (LoginEvent, Action)
Detection Engine ←→ ML Service  (ML scoring)
```
- Tất cả HTTP calls có `Internal-Secret` header
- Có retry logic + idempotency (event_id)

### 5. ML Service là stateless
- Model load từ disk vào memory lúc startup
- Logs ghi vào `ml-service-db` (optional)
- Background worker compute feature statistics hourly

## 📊 Liên kết với Schema

Xem chi tiết trong `ERD_v3.3.md`:

| Workflow | Tables liên quan |
|----------|------------------|
| WF-1 | `users`, `sessions`, `mfa_transactions`, `mfa_notifications` |
| WF-2 | `outbox_events` (core-db) → `login_attempts`, `risk_assessments`, `detection_logs`, `alerts` (detection-db) |
| WF-3 | `alerts`, `alert_timeline`, `soc_analysts` (cross-ref `users` via app) |
| WF-4 | `mfa_transactions`, `mfa_notifications`, `user_trusted_devices` |
| WF-5 | `sessions`, `audit_logs` |
| WF-6 | `model_versions`, `inference_logs`, `feature_statistics` |

## ⚠️ Cross-Database References

Một số FK references không thể enforce ở DB level do khác database:

| Column | Location | References (app-level) |
|--------|----------|------------------------|
| `policies.created_by` | detection-db | `users.id` (core-db) |
| `soc_analysts.user_id` | detection-db | `users.id` (core-db) |
| `alert_timeline.actor_id` | detection-db | `users.id` (core-db) |
| `model_versions.trained_by` | ml-service-db | `users.id` (core-db) |

Validate ở application layer qua HTTP calls tới core-app.

---

**Tác giả:** Khang (Sentinel Auth team)
**Ngày:** 2026-09-28
**Version:** v3.3
